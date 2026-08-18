/**
 * AtomicWorkflowExecutor — executes a single atomic workflow
 *
 * Lifecycle:
 *   1. Resolve workflow meta from Registry
 *   2. Inject runtime params into workflow JSON (prompt, images, seed, etc.)
 *   3. Upload reference images to ComfyUI input dir
 *   4. Submit the modified JSON to ComfyUI
 *   5. Poll for completion
 *   6. Download output files to outputDir
 *   7. Return structured result
 */

import fs from 'node:fs'
import path from 'node:path'
import { ComfyUIClient } from './client'
import { WorkflowRegistry } from './registry'
import { id } from '@/lib/id'
import {
  type ExecuteInputs,
  type ExecuteOptions,
  type ExecuteResult,
  type UploadResult,
  type WorkflowInputDef,
  type WorkflowOutput,
  WorkflowTimeoutError,
} from './types'

export class AtomicWorkflowExecutor {
  constructor(
    private client: ComfyUIClient,
    private registry: WorkflowRegistry,
  ) {}

  /**
   * Execute a single atomic workflow.
   *
   * @param workflowId - Name of the workflow in registry
   * @param inputs - Runtime parameter values keyed by meta.yaml input name
   * @param opts - Execution options
   */
  async execute(workflowId: string, inputs: ExecuteInputs, opts?: ExecuteOptions): Promise<ExecuteResult> {
    const resolved = this.registry.get(workflowId)
    const { meta, workflowJson } = resolved
    const startTime = Date.now()
    const outputDir = opts?.outputDir || process.env.OUTPUT_DIR || '/tmp/aicf-outputs'
    fs.mkdirSync(outputDir, { recursive: true })

    // 1. Inject parameters into workflow JSON
    const { injected, usedSeed } = await this.injectParams(workflowJson, meta.inputs, inputs)

    // 2. Submit
    const promptId = await this.client.submit(injected)

    // 3. Poll
    let history
    try {
      history = await this.client.pollResult(promptId, {
        timeout: opts?.timeout,
        onProgress: opts?.onProgress,
      })
    } catch (err) {
      if (err instanceof WorkflowTimeoutError) {
        // ComfyUI may have completed despite timeout — do a quick re-check.
        // If the workflow finished in the background, download outputs normally.
        try {
          console.log(`[AtomicExecutor] Timeout on ${promptId}, checking if completed...`);
          history = await this.client.pollResult(promptId, {
            timeout: 15_000,
          });
          console.log(`[AtomicExecutor] ${promptId} recovered after timeout`);
          // Falls through to normal output download below
        } catch (err2) {
          return {
            workflowId,
            promptId,
            status: 'timeout',
            duration: Date.now() - startTime,
            seed: usedSeed,
            outputs: [],
          };
        }
      } else {
        throw err;
      }
    }

    // 4. Parse and download outputs
    const outputs: WorkflowOutput[] = []
    const failedDownloads: Array<{ nodeId: number; filename: string; subfolder: string; error: string }> = []
    for (const outputDef of meta.outputs) {
      const nodeOutputs = history.outputs
      if (!nodeOutputs || typeof nodeOutputs !== 'object') break

      // Find the output node's data
      for (const [nodeId, nodeData] of Object.entries(nodeOutputs)) {
        // ComfyUI returns animated outputs (video/gif) under 'images' with animated=True,
        // and pure video under 'videos'. Check all applicable media keys.
        const mediaKeys: { key: string; matchType: string }[] = [
          { key: 'images', matchType: 'image' },
          { key: 'videos', matchType: 'video' },
          { key: 'audio', matchType: 'audio' },
        ]

        for (const { key, matchType } of mediaKeys) {
          // For video type, also match 'images' if files have `animated: True`
          const files = (nodeData as Record<string, unknown[]>)[key]
          if (!Array.isArray(files) || files.length === 0) continue

          // Filter: only process files matching the expected output type
          const matches = files.filter(f => {
            const info = f as Record<string, unknown>
            if (outputDef.type === matchType) return true
            // ComfyUI returns video files (.mp4/.webm/.gif) under 'images' key too.
            // Match them when the outputDef expects video.
            if (outputDef.type === 'video' && key === 'images') {
              const fn = String(info.filename || '')
              if (/\.(mp4|webm|gif)$/i.test(fn) || info.animated) return true
            }
            return false
          })

          for (const file of matches) {
            const { filename, subfolder = '', type = 'output' } = file as { filename: string; subfolder?: string; type?: string }

            try {
              const buf = await this.client.downloadOutput(Number(nodeId), filename, subfolder)

              const ext = path.extname(filename)
              const jobDir = path.join(outputDir, promptId)
              fs.mkdirSync(jobDir, { recursive: true })
              const localPath = path.join(jobDir, filename)

              // Avoid name collisions
              const finalPath = fs.existsSync(localPath)
                ? path.join(jobDir, `${path.basename(filename, ext)}_${id()}${ext}`)
                : localPath

              fs.writeFileSync(finalPath, buf)

              outputs.push({
                type: outputDef.type,
                localPath: finalPath,
                originalName: filename,
              })
            } catch (err) {
              const msg = err instanceof Error ? err.message : String(err);
              console.error(`[Executor] Download failed: ${filename} (node ${nodeId}) — ${msg}`);
              failedDownloads.push({ nodeId: Number(nodeId), filename, subfolder: subfolder || '', error: msg });
            }
          } // matches loop
        } // mediaKeys loop
      } // nodeOutputs loop
    } // outputDef loop

    return {
      workflowId,
      promptId,
      status: 'success',
      duration: Date.now() - startTime,
      seed: usedSeed,
      outputs,
      failedDownloads: failedDownloads.length > 0 ? failedDownloads : undefined,
    }
  }

  /**
   * Re-download specific output files from a completed ComfyUI prompt.
   */
  async downloadOutputsByPromptId(
    promptId: string,
    failedFiles: Array<{ nodeId: number; filename: string; subfolder: string }>,
    outputDir?: string,
  ): Promise<{ downloaded: WorkflowOutput[]; failed: typeof failedFiles }> {
    const dir = outputDir || process.env.OUTPUT_DIR || '/tmp/aicf-outputs';
    const jobDir = path.join(dir, promptId);
    fs.mkdirSync(jobDir, { recursive: true });
    const downloaded: WorkflowOutput[] = [];
    const failed: typeof failedFiles = [];
    for (const f of failedFiles) {
      try {
        const buf = await this.client.downloadOutput(f.nodeId, f.filename, f.subfolder);
        const finalPath = path.join(jobDir, f.filename);
        fs.writeFileSync(finalPath, buf);
        downloaded.push({
          type: /\.(mp4|webm|gif)$/i.test(f.filename) ? 'video' : 'image',
          localPath: finalPath,
          originalName: f.filename,
        });
      } catch (err) {
        console.error(`[Executor] Recovery download failed: ${f.filename}`);
        failed.push(f);
      }
    }
    return { downloaded, failed };
  }

  // ─── Parameter Injection ────────────────────────────────

  /**
   * Inject runtime parameters into a deep clone of the workflow JSON.
   *
   * For each input defined in meta.yaml:
   * - string/int/float → directly overwrite node.inputs.field
   * - image → upload file, then set node.inputs.image + node.inputs.subfolder
   * - Default values apply when the input is not provided
   */
  private async injectParams(
    workflowJson: Record<string, unknown>,
    inputDefs: WorkflowInputDef[],
    inputs: ExecuteInputs,
  ): Promise<{ injected: Record<string, unknown>; usedSeed: number }> {
    const injected = JSON.parse(JSON.stringify(workflowJson)) as Record<string, unknown>
    const uploaded = new Map<string, UploadResult>()  // cache deduplicated uploads
    let usedSeed = Date.now() % 1000000  // random seed fallback

    // Pre-upload a blank placeholder for unused LoadImage nodes
    const PLACEHOLDER_FILE = '/tmp/aicf-blank.png'
    if (!fs.existsSync(PLACEHOLDER_FILE)) {
      // 1x1 transparent PNG (minimal valid PNG)
      const blankPng = Buffer.from([
        0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A, // PNG signature
        0x00,0x00,0x00,0x0D,0x49,0x48,0x44,0x52, // IHDR chunk
        0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01, // 1x1 pixel
        0x08,0x06,0x00,0x00,0x00,0x1F,0x15,0xC4,0x89, // RGBA
        0x00,0x00,0x00,0x0B,0x49,0x44,0x41,0x54, // IDAT chunk (11 bytes)
        0x78,0x9C,0x63,0x60,0x00,0x02,0x00,0x00,0x05,0x00,0x01,0x7A,0x5E,0xAB,0x3F, // valid zlib compressed data
        0x00,0x00,0x00,0x00,0x49,0x45,0x4E,0x44,0xAE,0x42,0x60,0x82, // IEND
      ])
      fs.writeFileSync(PLACEHOLDER_FILE, blankPng)
    }

    // Provide a blank image path that executor will upload
    const blankPlaceholderPath = PLACEHOLDER_FILE

    for (const def of inputDefs) {
      const rawValue = inputs[def.name] ?? def.default
      if (rawValue === undefined && def.required) {
        throw new Error(`Required input "${def.name}" not provided for workflow`)
      }
      if (rawValue === undefined) {
        // Optional image input not provided: replace stale placeholder
        // with a 1x1 transparent blank so ComfyUI LoadImage doesn't crash.
        if (def.type === 'image') {
          const node = injected[String(def.node_id)] as Record<string, unknown> | undefined
          if (node) {
            const nodeInputs = (node.inputs || {}) as Record<string, unknown>
            if (!uploaded.has(blankPlaceholderPath)) {
              const result = await this.client.uploadImage(blankPlaceholderPath)
              uploaded.set(blankPlaceholderPath, result)
            }
            const upload = uploaded.get(blankPlaceholderPath)!
            nodeInputs[def.field] = upload.name
            node.inputs = nodeInputs
          }
        }
        continue
      }

      const node = injected[String(def.node_id)] as Record<string, unknown> | undefined
      if (!node) {
        console.warn(`[Executor] Node ${def.node_id} not found in workflow JSON, skipping "${def.name}"`)
        continue
      }

      const nodeInputs = (node.inputs || {}) as Record<string, unknown>

      switch (def.type) {
        case 'image': {
          const filePath = String(rawValue)
          if (!fs.existsSync(filePath)) {
            throw new Error(`Reference image not found: ${filePath}`)
          }

          // Deduplicate uploads (same file may be referenced by multiple inputs).
          // Use input name as unique prefix to avoid basename collisions
          // (e.g. all character refs saved as "character_reference.png").
          const cacheKey = `${def.name}::${filePath}`
          if (!uploaded.has(cacheKey)) {
            // Include directory UUID in uniqueName to prevent cross-character overwrites
            // when different characters share the same slot (e.g. character_ref_1).
            const dirId = path.dirname(filePath).split(path.sep).pop() || 'unknown';
            const result = await this.client.uploadImage(filePath, { uniqueName: `${def.name}_${dirId}` })
            uploaded.set(cacheKey, result)
          }

          const upload = uploaded.get(cacheKey)!
          nodeInputs[def.field] = upload.name
          if (upload.subfolder) {
            nodeInputs.subfolder = upload.subfolder
          }
          break
        }

        case 'string': {
          nodeInputs[def.field] = String(rawValue)
          break
        }

        case 'int': {
          const val = Math.round(Number(rawValue))
          nodeInputs[def.field] = val
          if (def.name === 'seed') usedSeed = val
          break
        }

        case 'float': {
          nodeInputs[def.field] = Number(rawValue)
          break
        }
      }

      node.inputs = nodeInputs
    }

    return { injected, usedSeed }
  }
}