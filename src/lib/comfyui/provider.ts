/**
 * ComfyUIProvider — AIProvider + VideoProvider implementation
 *
 * Maps AICF's provider interfaces to ComfyUI atomic workflows.
 *
 * AIProvider.generateImage():
 *   - 0 ref images  → qwen-2512-t2i
 *   - 1 ref image   → qwen-2511-edit (scene composite)
 *   - 2-3 ref images → qwen-2511-edit-plus
 *
 * VideoProvider.generateVideo():
 *   - firstFrame + lastFrame → h3-i2v
 *   - initialImage only      → h3-r2v
 *   - no images              → h3-t2v
 */

import path from 'node:path'
import { ComfyUIClient } from './client'
import { WorkflowRegistry } from './registry'
import { AtomicWorkflowExecutor } from './executor'
import { PipelineEngine } from '@/lib/pipeline-engine'
import type { PipelineInputs, PipelineResult } from '@/lib/pipeline-engine'
import type { AIProvider, ImageOptions, TextOptions } from '@/lib/ai/types'
import type { VideoProvider, VideoGenerateParams, VideoGenerateResult } from '@/lib/ai/types'

export interface ComfyUIProviderConfig {
  /** ComfyUI server URL */
  baseUrl?: string
  /** Directory containing atomic workflow subdirectories */
  workflowsDir: string
  /** Directory containing pipeline YAML definitions (optional — enables multi-step orchestration) */
  pipelinesDir?: string
  /** Default output directory for generated files */
  outputDir?: string
  /** Execution timeout per workflow (ms) */
  defaultTimeout?: number
  /** Directory containing pipeline scripts (Python post-processing) */
  scriptsDir?: string
}

export class ComfyUIProvider implements AIProvider, VideoProvider {
  private client: ComfyUIClient
  private registry: WorkflowRegistry
  private executor: AtomicWorkflowExecutor
  private pipelineEngine: PipelineEngine | null = null
  private outputDir: string
  private initialized = false

  /** Last pipeline execution result — callers can read intermediates from this */
  lastPipelineResult: PipelineResult | null = null

  constructor(private config: ComfyUIProviderConfig) {
    this.client = new ComfyUIClient({ baseUrl: config.baseUrl })
    this.registry = new WorkflowRegistry()
    this.executor = new AtomicWorkflowExecutor(this.client, this.registry)
    this.outputDir = config.outputDir || process.env.OUTPUT_DIR || './outputs'

    // Lazy-init pipeline engine if pipelines dir is configured
    if (config.pipelinesDir) {
      const scriptsDir = config.scriptsDir || path.join(process.cwd(), 'src', 'lib', 'pipeline-engine', 'scripts')
      this.pipelineEngine = new PipelineEngine({
        pipelinesDir: config.pipelinesDir,
        atomicExecutor: this.executor as any,
        registry: this.registry,
        client: this.client,
        scriptsDir,
        outputDir: this.outputDir,
      })
    }
  }

  /** Lazy-init: scan workflows directory on first use */
  private async ensureInitialized(): Promise<void> {
    if (this.initialized) return
    const loaded = await this.registry.scanFromDirectory(this.config.workflowsDir)
    if (loaded.length === 0) {
      throw new Error(`No atomic workflows found in ${this.config.workflowsDir}`)
    }
    console.log(`[ComfyUIProvider] Loaded ${loaded.length} workflows: ${loaded.join(', ')}`)

    // Verify connectivity
    const ok = await this.client.healthCheck()
    if (!ok) {
      throw new Error(`ComfyUI not reachable at ${this.config.baseUrl || 'http://localhost:8188'}`)
    }

    this.initialized = true

    // Load pipeline definitions after workflows are registered
    if (this.pipelineEngine) {
      const pipelinesDir = this.config.pipelinesDir
      if (pipelinesDir) {
        try {
          await this.pipelineEngine.loadFromDirectory(pipelinesDir)
          console.log(`[ComfyUIProvider] Loaded ${this.pipelineEngine.list().length} pipelines: ${this.pipelineEngine.list().join(', ')}`)
        } catch (err) {
          console.warn(`[ComfyUIProvider] Failed to load pipelines from ${pipelinesDir}: ${err}`)
        }
      }
    }
  }

  // ─── AIProvider ─────────────────────────────────────────

  /** Stub: text generation is delegated to IFF Proxy, not ComfyUI */
  async generateText(_prompt: string, _options?: TextOptions): Promise<string> {
    throw new Error('ComfyUIProvider does not support text generation. Use IFF Proxy (OpenAI-compatible) instead.')
  }

  /**
   * Generate an image via ComfyUI atomic workflow or multi-step pipeline.
   *
   * Pipeline mode (when options.pipeline is set):
   *   Routes to PipelineEngine for multi-step orchestration.
   *   Returns the pipeline's primary output.
   *
   * Atomic mode (default):
   *   Workflow selection by reference image count.
   */
  async generateImage(prompt: string, options?: ImageOptions): Promise<string> {
    // Pipeline mode: multi-step orchestration
    if (options?.pipeline && this.pipelineEngine) {
      await this.ensureInitialized()

      try {
        const pipelineInputs: PipelineInputs = {
          prompt,
          ...(options.referenceImages?.length
            ? { referenceImages: options.referenceImages }
            : {}),
          ...(options.pipelineParams || {}),
        }

        const result = await this.pipelineEngine.execute(options.pipeline, pipelineInputs, {
          outputDir: this.outputDir,
        })

        this.lastPipelineResult = result

        if (!result.primaryOutput) {
          throw new Error(`Pipeline '${options.pipeline}' produced no primary output`)
        }

        return result.primaryOutput
      } catch (err) {
        throw new Error(
          `Pipeline '${options.pipeline}' execution failed: ${err instanceof Error ? err.message : String(err)}`
        )
      }
    }

    // Atomic mode: single workflow
    await this.ensureInitialized()

    const refImages = options?.referenceImages || []

    let workflowId: string
    const inputs: Record<string, string | number | undefined> = { prompt }

    if (refImages.length === 0) {
      workflowId = 'qwen-2512-t2i'
    } else if (refImages.length === 1) {
      workflowId = 'qwen-2511-edit-scene-composite'
      // 2511-edit uses two prompts: scene_prompt and composite_prompt
      // When called via the generic generateImage interface, treat prompt as composite and auto-generate scene
      inputs.composite_prompt = prompt
      inputs.scene_prompt = `A scene with ${path.basename(refImages[0], path.extname(refImages[0]))}`
      inputs.character_ref = refImages[0]
    } else {
      workflowId = 'qwen-2511-edit-plus'
      inputs.composite_prompt = prompt
      inputs.scene_prompt = `A scene with multiple characters`
      for (let i = 0; i < Math.min(refImages.length, 3); i++) {
        inputs[`character_ref_${i + 1}`] = refImages[i]
      }
    }

    if (options?.size) {
      const parts = options.size.split('x')
      if (parts.length === 2) {
        inputs.width = parseInt(parts[0], 10)
        inputs.height = parseInt(parts[1], 10)
      }
    }

    const result = await this.executor.execute(workflowId, inputs, {
      outputDir: this.outputDir,
    })

    if (result.status !== 'success' || result.outputs.length === 0) {
      throw new Error(`Image generation failed: ${result.status}`)
    }

    return result.outputs[0].localPath
  }

  // ─── VideoProvider ──────────────────────────────────────

  /**
   * Generate a video via ComfyUI H3 atomic workflow.
   *
   * Mode selection:
   * - firstFrame + lastFrame present → h3-i2v (image-to-video with keyframes)
   * - initialImage present → h3-r2v (reference-to-video)
   * - no images → h3-t2v (text-to-video)
   */
  async generateVideo(params: VideoGenerateParams): Promise<VideoGenerateResult> {
    await this.ensureInitialized()

    let workflowId: string
    const inputs: Record<string, string | number | undefined> = {
      prompt: params.prompt,
    }

    if (params.firstFrame && params.lastFrame) {
      workflowId = 'h3-i2v'
      inputs.first_frame = params.firstFrame
    } else if (params.initialImage) {
      workflowId = 'h3-r2v'
      inputs.ref_image = params.initialImage
    } else {
      workflowId = 'h3-t2v'
    }

    // Approximate H3 length: 10s ≈ 73 frames at 24fps
    // H3 step size is 17 frames, so round to nearest step
    const totalFrames = Math.round(params.duration * 24)
    const stepped = Math.max(17, Math.round(totalFrames / 17) * 17)
    inputs.length = Math.min(stepped, 3600)

    this.ensureResolution(params, inputs)

    const result = await this.executor.execute(workflowId, inputs, {
      outputDir: this.outputDir,
    })

    if (result.status !== 'success' || result.outputs.length === 0) {
      throw new Error(`Video generation failed: ${result.status}`)
    }

    const videoOutput = result.outputs.find(o => o.type === 'video')
    if (!videoOutput) {
      throw new Error('Video generation produced no video output')
    }

    return { filePath: videoOutput.localPath }
  }

  // ─── Helpers ────────────────────────────────────────────

  private ensureResolution(params: VideoGenerateParams, inputs: Record<string, string | number | undefined>): void {
    const ratio = params.ratio || '16:9'
    switch (ratio) {
      case '16:9': inputs.width = 960; inputs.height = 544; break
      case '9:16': inputs.width = 544; inputs.height = 960; break
      case '1:1':  inputs.width = 768; inputs.height = 768; break
      case '4:3':  inputs.width = 960; inputs.height = 720; break
      default:
        const parts = ratio.split(':').map(Number)
        if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) {
          const base = 768
          inputs.width = Math.round(base * parts[0] / Math.max(parts[0], parts[1]))
          inputs.height = Math.round(base * parts[1] / Math.max(parts[0], parts[1]))
        }
    }
  }

  /** Re-scan workflows directory (call after hot-plugging new files) */
  async reloadWorkflows(): Promise<void> {
    this.initialized = false
    await this.ensureInitialized()
  }
}