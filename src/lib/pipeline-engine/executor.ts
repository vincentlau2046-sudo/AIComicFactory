import type { PipelineDefinition, PipelineInputs, PipelineResult, ResolveContext, StepDef, StepOutput, StepType } from './types'
import { PipelineError, StepExecutionError } from './types'
import { AtomicStepRunner } from './steps/atomic'
import { ScriptStepRunner } from './steps/script'
import { GPUScheduler } from './gpu-scheduler'
import type { AtomicWorkflowExecutor } from '@/lib/comfyui/executor'
import type { WorkflowRegistry } from '@/lib/comfyui/registry'
import { resolveTemplate } from './template'

/**
 * Topological DAG executor for pipeline steps.
 *
 * Execution model:
 * 1. Start with all steps that have no depends_on
 * 2. After each step completes, check if any waiting step has all deps satisfied
 * 3. GPU transitions are managed by GPUScheduler between steps
 * 4. Template resolution uses completed step outputs as context
 */
export class DAGExecutor {
  private atomicRunner: AtomicStepRunner
  private scriptRunner: ScriptStepRunner
  private gpu: GPUScheduler
  private registry: WorkflowRegistry
  private atomicExecutor: AtomicWorkflowExecutor

  constructor(deps: {
    atomicExecutor: AtomicWorkflowExecutor
    registry: WorkflowRegistry
    scriptsDir: string
    freeMemoryFn?: () => Promise<void>
  }) {
    this.atomicRunner = new AtomicStepRunner()
    this.scriptRunner = new ScriptStepRunner(deps.scriptsDir)
    this.gpu = new GPUScheduler(deps.freeMemoryFn)
    this.registry = deps.registry
    this.atomicExecutor = deps.atomicExecutor
  }

  async execute(
    pipeline: PipelineDefinition,
    inputs: PipelineInputs,
    opts: { outputDir: string; seed?: number }
  ): Promise<PipelineResult> {
    const startTime = Date.now()
    const completedSteps = new Map<string, StepOutput>()
    const effectiveSeed = inputs.seed ?? opts.seed ?? 42

    // Build resolve context (will be extended as steps complete)
    const buildCtx = (): ResolveContext => ({
      inputs: { ...inputs, seed: effectiveSeed },
      steps: completedSteps,
      env: { UPLOAD_DIR: opts.outputDir, ...process.env as Record<string, string | undefined> },
    })

    // Build dependency graph
    const stepsById = new Map<string, StepDef>()
    for (const step of pipeline.steps) {
      stepsById.set(step.id, step)
    }

    const completed = new Set<string>()
    const failed: string[] = []

    // Execute in topological order
    try {
      while (completed.size < pipeline.steps.length) {
        const ready = pipeline.steps.filter(
        step =>
          !completed.has(step.id) &&
          !failed.includes(step.id) &&
          (step.depends_on ?? []).every(dep => completed.has(dep))
      )

      if (ready.length === 0) {
        // Deadlock or unhandled failure
        const pending = pipeline.steps.filter(s => !completed.has(s.id))
        throw new PipelineError(
          `Pipeline deadlock: no steps ready. Pending: ${pending.map(s => s.id).join(', ')}`,
          pipeline.id
        )
      }

      // Execute ready steps (sequentially — no parallelism in v1)
      for (const step of ready) {
        const ctx = buildCtx()

        try {
          const result = await this.executeStep(step, ctx, opts)
          completedSteps.set(step.id, result)
          completed.add(step.id)
        } catch (err) {
          failed.push(step.id)

          const fallback = 'fallback' in step ? (step as any).fallback : undefined
          const isRequired = !('fallback' in step)

          if (fallback?.action === 'skip') {
            // Mark as completed with empty output
            completedSteps.set(step.id, {
              stepId: step.id,
              outputs: [],
              named: {},
              duration: 0,
            })
            completed.add(step.id)
            continue
          }

          if (fallback?.action === 'abort') {
            // Abort: immediately stop the pipeline
            throw new StepExecutionError(
              `Step "${step.id}" failed (abort fallback): ${err instanceof Error ? err.message : String(err)}`,
              pipeline.id,
              step.id,
              err instanceof Error ? err : undefined
            )
          }

          // For unimplemented fallback actions (retry, fallback), treat as required failure
          // This prevents silent deadlock — the step fails explicitly
          if (isRequired || fallback?.action === 'retry' || fallback?.action === 'fallback') {
            throw new StepExecutionError(
              `Step "${step.id}" failed (fallback action '${fallback?.action}' not yet implemented): ${err instanceof Error ? err.message : String(err)}`,
              pipeline.id,
              step.id,
              err instanceof Error ? err : undefined
            )
          }
        }
      }
      } // end while
    } finally {
      // Always free GPU after pipeline completes (success or failure)
      try {
        await this.gpu.finalize()
      } catch (gpuErr) {
        // GPU cleanup failure should not mask the original error
        console.warn(`[DAGExecutor] GPU finalize failed: ${gpuErr}`)
      }
    }

    // Build result (only reached on success)
    const primaryOutput = this.resolvePrimaryOutput(pipeline, buildCtx())
    const intermediates = this.collectIntermediates(pipeline, buildCtx())

    return {
      pipelineId: pipeline.id,
      primaryOutput,
      intermediates,
      steps: Array.from(completedSteps.values()),
      seed: effectiveSeed,
      totalDuration: Date.now() - startTime,
    }
  }

  private async executeStep(
    step: StepDef,
    ctx: ResolveContext,
    opts: { outputDir: string }
  ): Promise<StepOutput> {
    // Handle GPU transition
    if (step.type === 'atomic_workflow') {
      const meta = this.registry.get(step.workflow_id)
      await this.gpu.onStepTransition(meta?.meta.gpu_model)
    } else if (step.type === 'script') {
      // Script steps are CPU — still need to GPU transition
      await this.gpu.onStepTransition(undefined)
    }

    switch (step.type) {
      case 'atomic_workflow':
        return this.atomicRunner.execute(step, ctx, {
          executor: this.atomicExecutor,
          outputDir: opts.outputDir,
        })
      case 'script':
        return this.scriptRunner.execute(step, ctx, { outputDir: opts.outputDir })
      case 'parallel':
        throw new Error('Parallel steps not implemented in v1')
      default:
        throw new Error(`Unknown step type: ${(step as any).type}`)
    }
  }

  private resolvePrimaryOutput(
    pipeline: PipelineDefinition,
    ctx: ResolveContext
  ): string {
    if (!pipeline.outputs?.primary) {
      // Fallback: last step's first output
      const lastStep = pipeline.steps[pipeline.steps.length - 1]
      const stepOutput = ctx.steps.get(lastStep.id)
      return stepOutput?.outputs[0] ?? ''
    }

    // Resolve primary template
    const resolved = resolveTemplate(pipeline.outputs.primary, ctx)
    return resolved != null ? String(resolved) : ''
  }

  private collectIntermediates(
    pipeline: PipelineDefinition,
    ctx: ResolveContext
  ): Record<string, string> {
    const intermediates: Record<string, string> = {}

    // Include all step outputs as intermediates
    for (const [stepId, output] of ctx.steps) {
      if (output.outputs.length > 0) {
        intermediates[stepId] = output.outputs[0]
      }
      for (const [name, path] of Object.entries(output.named)) {
        intermediates[`${stepId}.${name}`] = path
      }
    }

    return intermediates
  }
}