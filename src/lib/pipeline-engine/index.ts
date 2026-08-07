import path from 'node:path'
import type { PipelineDefinition, PipelineInputs, PipelineResult } from './types'
import { PipelineError } from './types'
import { PipelineLoader } from './loader'
import { DAGExecutor } from './executor'

// ─── Re-exported types for consumers ────────────────────
export type { PipelineInputs, PipelineResult }
import type { AtomicWorkflowExecutor } from '@/lib/comfyui/executor'
import type { WorkflowRegistry } from '@/lib/comfyui/registry'
import type { ComfyUIClient } from '@/lib/comfyui/client'

/**
 * PipelineEngine — multi-step orchestration engine for ComfyUI atomic workflows.
 *
 * Loads pipeline YAML definitions, resolves template expressions, manages GPU state,
 * and executes steps in topological order.
 *
 * Used by ComfyUIProvider as its internal orchestration layer for pipelines
 * that require multiple atomic workflows (e.g., character-image: T2I → multiangle × 3 → merge).
 */
export class PipelineEngine {
  private pipelines = new Map<string, PipelineDefinition>()
  private executor: DAGExecutor
  private loader: PipelineLoader
  private client: ComfyUIClient
  private defaultOutputDir: string

  constructor(config: {
    pipelinesDir: string
    atomicExecutor: AtomicWorkflowExecutor
    registry: WorkflowRegistry
    client: ComfyUIClient
    scriptsDir?: string
    outputDir?: string
  }) {
    this.loader = new PipelineLoader()
    this.client = config.client
    this.defaultOutputDir = config.outputDir || '/tmp/aicf-pipelines'
    this.executor = new DAGExecutor({
      atomicExecutor: config.atomicExecutor,
      registry: config.registry,
      scriptsDir: config.scriptsDir || path.join(process.cwd(), 'src', 'lib', 'pipeline-engine', 'scripts'),
      freeMemoryFn: () => config.client.freeMemory(),
    })
  }

  // ─── Loading ──────────────────────────────────────────────

  async loadFromDirectory(dir?: string): Promise<void> {
    const pipelinesDir = dir ?? this.getDefaultPipelinesDir()
    const defs = await this.loader.loadFromDirectory(pipelinesDir)
    for (const def of defs) {
      this.pipelines.set(def.id, def)
    }
  }

  async loadFromFile(filePath: string): Promise<PipelineDefinition> {
    const def = await this.loader.loadFromFile(filePath)
    this.pipelines.set(def.id, def)
    return def
  }

  // ─── Query ────────────────────────────────────────────────

  has(pipelineId: string): boolean {
    return this.pipelines.has(pipelineId)
  }

  get(pipelineId: string): PipelineDefinition {
    const def = this.pipelines.get(pipelineId)
    if (!def) throw new PipelineError(`Pipeline "${pipelineId}" not found`, pipelineId)
    return def
  }

  list(): string[] {
    return Array.from(this.pipelines.keys())
  }

  // ─── Execution ────────────────────────────────────────────

  async execute(
    pipelineId: string,
    inputs: PipelineInputs,
    opts?: { outputDir?: string; seed?: number }
  ): Promise<PipelineResult> {
    const def = this.get(pipelineId)
    return this.executor.execute(def, inputs, {
      outputDir: opts?.outputDir ?? this.defaultOutputDir,
      seed: opts?.seed,
    })
  }

  // ─── Internal ─────────────────────────────────────────────

  private getDefaultPipelinesDir(): string {
    return path.join(process.cwd(), 'src', 'lib', 'pipeline-engine', 'pipelines')
  }
}