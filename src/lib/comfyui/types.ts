/**
 * ComfyUIProvider — type definitions
 *
 * Core types for the ComfyUI atomic workflow execution layer.
 */

// ─── Workflow Metadata ────────────────────────────────────

export interface WorkflowInputDef {
  node_id: number
  field: string
  name: string
  type: 'string' | 'int' | 'float' | 'image'
  required?: boolean
  default?: string | number
  description?: string
  constraints?: {
    min?: number
    max?: number
    step?: number
  }
}

export interface WorkflowOutputDef {
  name: string
  type: 'image' | 'video' | 'audio'
  description?: string
  filename_pattern?: string
}

export interface WorkflowMeta {
  name: string
  display_name?: string
  description?: string
  gpu_model?: string
  models?: { name: string; type: string }[]
  inputs: WorkflowInputDef[]
  outputs: WorkflowOutputDef[]
}

export interface ResolvedWorkflow {
  meta: WorkflowMeta
  workflowJson: Record<string, unknown>
  sourcePath: string
}

// ─── Execution ────────────────────────────────────────────

export interface ExecuteInputs {
  [key: string]: string | number | undefined
}

export interface ExecuteOptions {
  timeout?: number
  outputDir?: string
  onProgress?: (info: ProgressInfo) => void
}

export interface ProgressInfo {
  promptId: string
  progress: number  // 0-100
  currentNode?: string
}

export interface WorkflowOutput {
  type: 'image' | 'video' | 'audio'
  localPath: string
  originalName: string
}

export interface ExecuteResult {
  workflowId: string
  promptId: string
  status: 'success' | 'timeout' | 'error'
  duration: number  // ms
  seed: number
  outputs: WorkflowOutput[]
  failedDownloads?: Array<{ nodeId: number; filename: string; subfolder: string; error: string }>
}

export interface QueueStatus {
  running: number
  pending: number
}

// ─── Errors ───────────────────────────────────────────────

export class WorkflowTimeoutError extends Error {
  constructor(public promptId: string, timeout: number) {
    super(`Workflow ${promptId} timed out after ${timeout}ms`)
    this.name = 'WorkflowTimeoutError'
  }
}

export class WorkflowNotFoundError extends Error {
  constructor(workflowId: string) {
    super(`Workflow "${workflowId}" not found in registry`)
    this.name = 'WorkflowNotFoundError'
  }
}

export class ModelLoadError extends Error {
  constructor(public modelName: string, cause?: Error) {
    super(`Model "${modelName}" failed to load${cause ? `: ${cause.message}` : ''}`)
    this.name = 'ModelLoadError'
  }
}

export class ComfyUIConnectionError extends Error {
  constructor(public baseUrl: string, cause?: Error) {
    super(`Cannot connect to ComfyUI at ${baseUrl}${cause ? `: ${cause.message}` : ''}`)
    this.name = 'ComfyUIConnectionError'
  }
}

// ─── Upload ───────────────────────────────────────────────

export interface UploadResult {
  /** ComfyUI 实际返回的字段名是 'name' 而非 'filename' */
  name: string
  subfolder: string
  type?: string
}

// ─── ComfyUI API Responses ────────────────────────────────

export interface PromptResponse {
  prompt_id: string
  number: number
  node_errors?: Record<string, unknown>
}

export interface HistoryResponse {
  [promptId: string]: {
    prompt: unknown
    outputs: Record<string, {
      images?: { filename: string; subfolder: string; type: string }[]
      videos?: { filename: string; subfolder: string; type: string }[]
      audio?: { filename: string; subfolder: string; type: string }[]
    }>
    status: {
      status_str: string
      completed: boolean
      messages?: [string, unknown][]
    }
  }
}

export interface SystemStatsResponse {
  system: {
    os: string
    comfyui_version: string
    python: string
    pytorch: string
    embedded_python: boolean
    args: string[]
  }
  devices: {
    name: string
    type: string
    index: number
    vram_total: number
    vram_free: number
    torch_version: string
  }[]
}

// ─── Provider Interface Overrides ─────────────────────────

export interface ImageGenerationInput {
  prompt: string
  negative_prompt?: string
  referenceImages?: string[]
  size?: string
  seed?: number
}

export interface VideoGenerationInput {
  prompt: string
  firstFrame?: string
  lastFrame?: string
  initialImage?: string
  referenceImages?: string[]
  duration: number
  width?: number
  height?: number
  seed?: number
}