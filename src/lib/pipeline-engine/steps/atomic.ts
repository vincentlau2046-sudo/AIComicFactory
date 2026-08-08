import type { WorkflowRegistry } from '@/lib/comfyui/registry'
import type { AtomicWorkflowExecutor } from '@/lib/comfyui/executor'
import { resolveInputs, resolveOutputPaths } from '../template'
import type { AtomicStepDef, ResolveContext, StepOutput } from '../types'

/**
 * Executes an atomic_workflow step by resolving templates against pipeline
 * context, then delegating to AtomicWorkflowExecutor.
 *
 * The resolved input keys must match the meta.yaml `name` fields.
 * The executor handles image upload internally via injectParams().
 */
export class AtomicStepRunner {
  async execute(
    step: AtomicStepDef,
    ctx: ResolveContext,
    deps: {
      executor: AtomicWorkflowExecutor
      outputDir?: string
    }
  ): Promise<StepOutput> {
    const startTime = Date.now()
    const allOutputs: string[] = []
    const namedOutputMap: Record<string, string> = {}
    const count = step.count ?? 1

    for (let i = 0; i < count; i++) {
      const iterCtx: ResolveContext = {
        ...ctx,
        iter: { index: i, count },
      }

      const resolvedInputs = resolveInputs(step.inputs, iterCtx) as Record<string, string | number>

      const maxRetries = step.retry?.max ?? 0
      let lastError: Error | undefined

      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          const result = await deps.executor.execute(step.workflow_id, resolvedInputs, {
            outputDir: deps.outputDir,
          })

          // Check for non-success status (timeout, error, etc.)
          if (result.status !== 'success' || result.outputs.length === 0) {
            throw new Error(`Atomic workflow '${step.workflow_id}' returned status: ${result.status}`)
          }

          // Collect outputs
          for (const output of result.outputs) {
            if (!allOutputs.includes(output.localPath)) {
              allOutputs.push(output.localPath)
            }
          }

          // Map named outputs via resolveOutputPaths (resolves ${outputs[i].localPath} templates)
          const resolvedOutputs = resolveOutputPaths(step.outputs, result.outputs.map(o => o.localPath))
          for (const [name, path] of Object.entries(resolvedOutputs)) {
            if (typeof path === 'string' && path && !namedOutputMap[name]) {
              namedOutputMap[name] = path
            }
          }

          lastError = undefined
          break
        } catch (err) {
          lastError = err instanceof Error ? err : new Error(String(err))
          if (attempt < maxRetries) {
            await sleep(step.retry!.delay)
          }
        }
      }

      if (lastError) {
        const { StepRetryExceeded } = await import('../types')
        throw new StepRetryExceeded(ctx.pipelineId ?? 'unknown', step.id, maxRetries, { cause: lastError })
      }
    }

    return {
      stepId: step.id,
      outputs: allOutputs,
      named: namedOutputMap,
      workflowId: step.workflow_id,
      duration: Date.now() - startTime,
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}