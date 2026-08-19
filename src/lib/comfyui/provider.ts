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
 *   - initialImage only      → h3-r2v (single-ref)
 *   - initialImage + referenceImages → h3-r2v (multi-ref, dynamic workflow)
 *   - no images              → h3-t2v
 */

import fs from 'node:fs'
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
    this.outputDir = path.resolve(config.outputDir || process.env.OUTPUT_DIR || './outputs')

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
    await this.ensureInitialized()
    if (options?.pipeline && this.pipelineEngine) {
      await this.ensureInitialized()

      try {
        const pipelineInputs: PipelineInputs = {
          prompt,
          ...(options.referenceImages?.length
            ? { referenceImages: options.referenceImages }
            : {}),
          ...(options.pipelineParams || {}),
          ...(options.size ? (() => {
            const parts = options.size!.split('x');
            if (parts.length === 2) {
              const w = parseInt(parts[0], 10);
              const h = parseInt(parts[1], 10);
              return { width: w, height: h };
            }
            return {};
          })() : {}),
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

    // Pipeline mode requested but engine not configured
    if (options?.pipeline && !this.pipelineEngine) {
      console.warn(`[ComfyUIProvider] Pipeline '${options.pipeline}' requested but pipeline engine not configured (missing pipelinesDir). Falling back to atomic mode.`)
    }

    const refImages = options?.referenceImages || []

    let workflowId: string
    const inputs: Record<string, string | number | undefined> = { prompt }

    if (refImages.length === 0) {
      // 0 ref → 纯文生图，不引入随机人物
      workflowId = 'qwen-2512-t2i'
    } else {
      // ≥1 ref → edit-plus，带角色参考图合成
      workflowId = 'qwen-2511-edit-plus'
      // Build composite prompt with Picture N: baseName references.
      // Picture N maps to imageN in node config (hard binding).
      // Using JUST baseName (no visualHint) prevents visual distortion.
      const picRefs = refImages.map((_, i) => {
        const label = options?.referenceLabels?.[i] || `角色${i + 1}`;
        return `Picture ${i + 1}: ${label}`;
      });
      inputs.composite_prompt = `${picRefs.join(", ")}. ${prompt}`;
      const compatLabel = (options?.referenceLabels || []).join(",");
      console.log(`[H3-ComfyUI] edit-plus composite: ${refImages.length} refs, labels=[${compatLabel}], picRefs=[${picRefs.join("; ")}]`);
      inputs.scene_prompt = options?.scenePrompt || prompt
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
   * Mode dispatch:
   * - firstFrame + lastFrame present → h3-i2v (image-to-video with keyframes)
   * - initialImage present → h3-r2v (reference-to-video, single or multi-ref)
   * - no images → h3-t2v (text-to-video)
   */
  async generateVideo(params: VideoGenerateParams): Promise<VideoGenerateResult> {
    await this.ensureInitialized()

    if (params.firstFrame && params.lastFrame) {
      return this.generateKeyframeVideo(params)
    }

    if (params.initialImage) {
      // Deduplicate: initialImage may also appear in referenceImages
      const seen = new Set<string>()
      const allRefImages: string[] = []
      for (const img of [params.initialImage, ...(params.referenceImages || [])]) {
        if (!seen.has(img)) {
          seen.add(img)
          allRefImages.push(img)
        }
      }
      return this.generateReferenceVideo(params, allRefImages)
    }

    return this.generateTextVideo(params)
  }

  /**
   * Keyframe (I2V) mode: firstFrame + lastFrame → h3-i2v.
   * Uses standard meta.yaml-driven executor path.
   */
  private async generateKeyframeVideo(
    params: VideoGenerateParams & { firstFrame: string; lastFrame: string }
  ): Promise<VideoGenerateResult> {
    const inputs: Record<string, string | number | undefined> = {
      prompt: params.prompt,
      first_frame: params.firstFrame,
      last_frame: params.lastFrame,
    }
    this.computeDuration(params.duration, params.ratio || '16:9', inputs)
    return this.executeAndDownload('h3-i2v', inputs)
  }

  /**
   * Text-to-video mode: no images → h3-t2v.
   * Uses standard meta.yaml-driven executor path.
   */
  private async generateTextVideo(params: VideoGenerateParams): Promise<VideoGenerateResult> {
    const inputs: Record<string, string | number | undefined> = {
      prompt: params.prompt,
    }
    this.computeDuration(params.duration, params.ratio || '16:9', inputs)
    return this.executeAndDownload('h3-t2v', inputs)
  }

  /**
   * Reference-to-video (R2V) mode: dynamic multi-ref workflow.
   *
   * Builds a custom workflow JSON on-the-fly with N LoadImage nodes,
   * uploads reference images, and submits directly to ComfyUI.
   * Does NOT use the standard executor path — the workflow JSON
   * is dynamically generated to accommodate variable image counts.
   */
  private async generateReferenceVideo(
    params: VideoGenerateParams,
    allRefImages: string[]
  ): Promise<VideoGenerateResult> {
    const { meta, workflowJson } = this.registry.get('h3-r2v')

    // 1. Build dynamic workflow: clone template + add N LoadImage nodes
    const { workflow: modified, imageNodes } = this.buildMultiRefWorkflow(
      workflowJson, allRefImages.length
    )

    // 2. Upload each reference image to ComfyUI, inject filename into LoadImage node
    for (let i = 0; i < allRefImages.length; i++) {
      const filePath = allRefImages[i]
      if (!fs.existsSync(filePath)) {
        throw new Error(`[R2V] Reference image not found: ${filePath}`)
      }
      const uploaded = await this.client.uploadImage(filePath, {
        uniqueName: `r2v_ref_${i + 1}`,
      })
      const node = modified[String(imageNodes[i])] as any
      node.inputs.image = uploaded.name
      if (uploaded.subfolder) {
        node.inputs.subfolder = uploaded.subfolder;
      }
    }

    // 3. Inject non-image params into MiniMaxH3ReferenceToVideo node
    const vaNodeId = this.findNodeByType(modified, 'MiniMaxH3ReferenceToVideo')
    if (!vaNodeId) throw new Error('MiniMaxH3ReferenceToVideo node not found in R2V workflow')
    const vaNode = modified[String(vaNodeId)] as any
    vaNode.inputs.prompt = params.prompt

    const { width, height } = this.resolveResolution(params.ratio || '16:9')
    vaNode.inputs.width = width
    vaNode.inputs.height = height

    const totalFrames = Math.round((params.duration || 5) * 24)
    vaNode.inputs.length = Math.min(Math.max(17, Math.round(totalFrames / 17) * 17), 3600)

    console.log(
      `[R2V] Submitting: ${allRefImages.length} ref images, ${params.duration}s, ${width}x${height}, prompt=${params.prompt.slice(0, 80)}...`
    )

    // ── DEBUG: dump submitted ref_images structure ──
    const vaNodeForDebug = modified[String(vaNodeId)] as any;
    console.log(`[R2V-DEBUG] MiniMaxH3ReferenceToVideo node ${vaNodeId} inputs:`);
    console.log(`[R2V-DEBUG]   ref_images =`, JSON.stringify(vaNodeForDebug.inputs.ref_images));
    for (const key of Object.keys(vaNodeForDebug.inputs)) {
      if (key.startsWith('ref_image_')) {
        console.log(`[R2V-DEBUG]   direct input ${key} =`, JSON.stringify(vaNodeForDebug.inputs[key]));
      }
    }
    for (const nid of imageNodes) {
      const ln = modified[String(nid)] as any;
      console.log(`[R2V-DEBUG]   LoadImage node ${nid}: image=${ln.inputs.image}, subfolder=${ln.inputs.subfolder || '(none)'}`);
    }
    // ── END DEBUG ──

    // 4. Submit + poll
    const promptId = await this.client.submit(modified)
    const history = await this.client.pollResult(promptId, {
      timeout: 1_800_000, // 30 min
    })

    // 5. Download video output (replicate executor download logic for video type)
    const outputDir = this.outputDir
    const jobDir = path.join(outputDir, promptId)
    fs.mkdirSync(jobDir, { recursive: true })

    for (const outputDef of meta.outputs) {
      const nodeOutputs = history.outputs
      if (!nodeOutputs || typeof nodeOutputs !== 'object') continue

      for (const [, nodeData] of Object.entries(nodeOutputs)) {
        const keys: string[] = ['videos', 'images']
        for (const key of keys) {
          const files = (nodeData as Record<string, unknown[]>)[key]
          if (!Array.isArray(files)) continue
          for (const file of files) {
            const f = file as Record<string, unknown>
            const filename = f.filename as string
            if (!filename) continue
            // Match video type outputs only
            const isVideo = /\.(mp4|webm)$/i.test(filename) || f.animated
            const matchesType = outputDef.type === 'video' && isVideo
            if (!matchesType && outputDef.type !== 'video') continue

            try {
              const buf = await this.client.downloadOutput(
                Number(Object.keys(nodeOutputs)[0]),
                filename,
                (f.subfolder as string) || ''
              )
              const localPath = path.join(jobDir, filename)
              fs.writeFileSync(localPath, buf)
              return { filePath: localPath }
            } catch (err) {
              console.error(`[R2V] Download failed: ${filename} — ${err}`)
            }
          }
        }
      }
    }

    throw new Error('R2V generation produced no video output')
  }

  /**
   * Submit a standard (non-dynamic) workflow via the executor, then download video.
   */
  private async executeAndDownload(
    workflowId: string,
    inputs: Record<string, string | number | undefined>
  ): Promise<VideoGenerateResult> {
    const result = await this.executor.execute(workflowId, inputs, {
      outputDir: this.outputDir,
      timeout: 1_800_000,
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

  // ─── Dynamic Workflow Builders ──────────────────────────

  /**
   * Build a modified R2V workflow with N LoadImage nodes wired to the
   * MiniMaxH3ReferenceToVideo node's ref_images dict.
   *
   * The base workflow template has ref_images: {} (empty) on the
   * MiniMaxH3ReferenceToVideo node. This method clones the template,
   * adds N LoadImage nodes, and populates the ref_images dict with
   * links to those nodes.
   */
  private buildMultiRefWorkflow(
    baseWorkflow: Record<string, any>,
    imageCount: number
  ): { workflow: Record<string, any>; imageNodes: number[] } {
    const wf = JSON.parse(JSON.stringify(baseWorkflow))

    const vaNodeId = this.findNodeByType(wf, 'MiniMaxH3ReferenceToVideo')
    if (!vaNodeId) throw new Error('MiniMaxH3ReferenceToVideo node not found in workflow template')

    const existingIds = Object.keys(wf).map(Number).filter(n => !isNaN(n))
    const lastNodeId = Math.max(...existingIds)
    const clamped = Math.min(imageCount, 9); // MiniMax H3: max 9 reference images
    if (imageCount > 9) {
      console.warn(`[R2V] buildMultiRefWorkflow: clamping ${imageCount} images to 9 (H3 limit)`);
    }

    const imageNodes: number[] = []
    const refLinks: Record<string, any> = {}

    for (let i = 0; i < clamped; i++) {
      const nodeId = lastNodeId + 1 + i
      wf[String(nodeId)] = {
        class_type: 'LoadImage',
        inputs: { image: 'placeholder.png' },
      }
      imageNodes.push(nodeId)
      refLinks[`ref_image_${i + 1}`] = [String(nodeId), 0]
    }

    // Write ref_image_N as direct inputs (Autogrow format, ComfyUI 0.30+)
    // Packed into ref_images dict by execute() via **kwargs
    for (const [key, value] of Object.entries(refLinks)) {
      wf[String(vaNodeId)].inputs[key] = value;
    }

    return { workflow: wf, imageNodes }
  }

  /** Find the first node with the given class_type, return its id or null. */
  private findNodeByType(
    workflow: Record<string, any>,
    classType: string
  ): number | null {
    for (const [id, node] of Object.entries(workflow)) {
      if (node && typeof node === 'object' && node.class_type === classType) {
        return Number(id)
      }
    }
    return null
  }

  // ─── Resolution & Duration Helpers ──────────────────────

  /** Compute width, height, length from ratio + duration, write into inputs map. */
  private computeDuration(
    duration: number,
    ratio: string,
    inputs: Record<string, string | number | undefined>
  ): void {
    const { width, height } = this.resolveResolution(ratio)
    inputs.width = width
    inputs.height = height

    const totalFrames = Math.round(duration * 24)
    inputs.length = Math.min(Math.max(17, Math.round(totalFrames / 17) * 17), 3600)
  }

  /** Resolve aspect ratio to (width, height) for H3 native resolution grid. */
  private resolveResolution(ratio: string): { width: number; height: number } {
    switch (ratio) {
      case '16:9': return { width: 960, height: 544 }
      case '9:16': return { width: 544, height: 960 }
      case '1:1':  return { width: 768, height: 768 }
      case '4:3':  return { width: 960, height: 720 }
      default: {
        const parts = ratio.split(':').map(Number)
        if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) {
          const base = 768
          return {
            width: Math.round(base * parts[0] / Math.max(parts[0], parts[1])),
            height: Math.round(base * parts[1] / Math.max(parts[0], parts[1])),
          }
        }
        return { width: 960, height: 544 }
      }
    }
  }

  /** Re-scan workflows directory (call after hot-plugging new files) */
  async reloadWorkflows(): Promise<void> {
    this.initialized = false
    await this.ensureInitialized()
  }
}