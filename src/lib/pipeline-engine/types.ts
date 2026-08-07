// ─── Pipeline Definition (from YAML) ─────────────────────────

export type StepType = 'atomic_workflow' | 'script' | 'parallel'

export interface RetryPolicy {
  max: number
  delay: number // ms
}

export interface Fallback {
  action: 'skip' | 'abort' | 'retry' | 'fallback' // 'retry'/'fallback' accepted in YAML but not yet implemented in executor
  workflow_id?: string
  delay?: number
}

export interface AtomicStepDef {
  id: string
  type: 'atomic_workflow'
  workflow_id: string
  description?: string
  depends_on?: string[]
  count?: number // >1 = fan-out; iter.index/iter.count available in templates
  inputs: Record<string, string | number | boolean | null> // raw template strings or literals
  outputs: Record<string, string> // output_name → template resolving to file path
  retry?: RetryPolicy
  fallback?: Fallback
}

export interface ScriptStepDef {
  id: string
  type: 'script'
  script: string // relative path under scripts/ or bin name
  description?: string
  depends_on?: string[]
  inputs: Record<string, string | number | boolean | null>
  outputs: Record<string, string>
  retry?: RetryPolicy
}

export interface ParallelStepDef {
  id: string
  type: 'parallel'
  steps: (AtomicStepDef | ScriptStepDef)[]
  description?: string
  depends_on?: string[]
}

export type StepDef = AtomicStepDef | ScriptStepDef | ParallelStepDef

export interface PipelineDefinition {
  id: string
  display_name?: string
  description?: string
  version: string
  steps: StepDef[]
  outputs?: {
    primary: string
    intermediates?: Record<string, string>
  }
}

// ─── Runtime Types ───────────────────────────────────────────

export interface PipelineInputs {
  prompt: string
  seed?: number
  referenceImages?: string[]
  [key: string]: unknown
}

export interface StepOutput {
  stepId: string
  outputs: string[] // local file paths
  named: Record<string, string> // named outputs from the step def
  workflowId?: string
  duration: number
}

export interface PipelineResult {
  pipelineId: string
  primaryOutput: string
  intermediates: Record<string, string>
  steps: StepOutput[]
  seed: number
  totalDuration: number
}

export interface ResolveContext {
  inputs: PipelineInputs
  steps: Map<string, StepOutput>
  env: Record<string, string | undefined>
  iter?: { index: number; count: number }
  pipelineId?: string
}

// ─── Error Classes ───────────────────────────────────────────

export class PipelineError extends Error {
  constructor(
    message: string,
    public readonly pipelineId: string,
    public readonly stepId?: string,
    cause?: Error
  ) {
    super(message, cause ? { cause } : undefined)
    this.name = 'PipelineError'
  }
}

export class StepExecutionError extends PipelineError {
  constructor(
    message: string,
    pipelineId: string,
    stepId: string,
    cause?: Error
  ) {
    super(message, pipelineId, stepId, cause)
    this.name = 'StepExecutionError'
  }
}

export class StepRetryExceeded extends StepExecutionError {
  constructor(pipelineId: string, stepId: string, maxRetries: number, opts?: { cause?: Error }) {
    super(
      `Step ${stepId} failed after ${maxRetries} retries (${maxRetries + 1} attempts)`,
      pipelineId,
      stepId,
      opts?.cause
    )
    this.name = 'StepRetryExceeded'
  }
}

// ─── GPU Model Classification ────────────────────────────────

export type ModelFamily = 'qwen-image' | 'minimax-h3' | 'cpu' | 'unknown'

export const MODEL_FAMILY: Record<string, ModelFamily> = {
  qwen_2512: 'qwen-image',
  qwen_2511: 'qwen-image',
  minimax_h3: 'minimax-h3',
}

export function classifyModelFamily(metaGpuModel?: string): ModelFamily {
  if (!metaGpuModel) return 'cpu'
  // Exact match first
  if (MODEL_FAMILY[metaGpuModel]) return MODEL_FAMILY[metaGpuModel]
  // Prefix match for variants (e.g. qwen_2511_edit_plus → qwen-image)
  for (const [prefix, family] of Object.entries(MODEL_FAMILY)) {
    if (metaGpuModel.startsWith(prefix)) return family
  }
  // Unknown GPU model — treat as GPU-requiring (fail-safe: triggers freeMemory)
  console.warn(`[PipelineEngine] Unknown gpu_model "${metaGpuModel}", classifying as 'unknown' (will trigger GPU memory free)`)
  return 'unknown'
}