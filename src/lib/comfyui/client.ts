/**
 * ComfyUIClient — low-level HTTP REST client for ComfyUI
 *
 * Protocol: POST /prompt → GET /history/{id} polling loop
 * No WebSocket. Polling with jitter is sufficient for H3's 162s runtime.
 */

import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import {
  type HistoryResponse,
  type PromptResponse,
  type QueueStatus,
  type SystemStatsResponse,
  type UploadResult,
  ComfyUIConnectionError,
} from './types'

export interface ClientOptions {
  baseUrl?: string
  defaultTimeout?: number
  pollInterval?: number
  maxRetries?: number
}

const DEFAULTS = {
  baseUrl: 'http://localhost:8188',
  defaultTimeout: 300_000, // 5 min
  pollInterval: 500,
  maxRetries: 3,
}

export class ComfyUIClient {
  private baseUrl: string
  private defaultTimeout: number
  private pollInterval: number
  private maxRetries: number

  constructor(opts?: ClientOptions) {
    this.baseUrl = (opts?.baseUrl || DEFAULTS.baseUrl).replace(/\/+$/, '')
    this.defaultTimeout = opts?.defaultTimeout ?? DEFAULTS.defaultTimeout
    this.pollInterval = opts?.pollInterval ?? DEFAULTS.pollInterval
    this.maxRetries = opts?.maxRetries ?? DEFAULTS.maxRetries
  }

  // ─── Core API ─────────────────────────────────────────────

  /** Submit a workflow and return the prompt_id */
  async submit(workflow: object): Promise<string> {
    const body = { prompt: workflow, client_id: `aicf-${randomUUID().slice(0, 8)}` }
    const data = await this.request<PromptResponse>('POST', '/prompt', body)
    return data.prompt_id
  }

  /** Poll for execution result until completion or timeout */
  async pollResult(
    promptId: string,
    opts?: { timeout?: number; interval?: number; onProgress?: (info: { promptId: string; progress: number; currentNode?: string }) => void },
  ): Promise<HistoryResponse[string]> {
    const timeout = opts?.timeout ?? this.defaultTimeout
    const interval = opts?.interval ?? this.pollInterval
    const deadline = Date.now() + timeout

    while (Date.now() < deadline) {
      const data = await this.request<HistoryResponse>('GET', `/history/${promptId}`)

      // History endpoint returns {} until the prompt is completed
      if (data[promptId]) {
        const result = data[promptId]
        if (result.status.completed) {
          return result
        }
        // Even if not marked completed yet, the entry exists — continue polling
      }

      // Try to extract progress from queue if available
      if (opts?.onProgress) {
        try {
          const queue = await this.getQueue()
          if (queue.running > 0) {
            opts.onProgress({
              promptId,
              progress: 50, // rough estimate
            })
          }
        } catch {
          // non-blocking
        }
      }

      await sleep(interval)
    }

    throw new (await import('./types')).WorkflowTimeoutError(promptId, timeout)
  }

  /** Upload a local image file to ComfyUI's input directory */
  async uploadImage(filePath: string): Promise<UploadResult> {
    if (!fs.existsSync(filePath)) {
      throw new Error(`Image file not found: ${filePath}`)
    }

    const ext = path.extname(filePath).toLowerCase()
    const supportedExts = ['.png', '.jpg', '.jpeg', '.webp', '.bmp']
    if (!supportedExts.includes(ext)) {
      throw new Error(`Unsupported image format: ${ext}. Supported: ${supportedExts.join(', ')}`)
    }

    const formData = new FormData()
    const blob = new Blob([fs.readFileSync(filePath)], { type: `image/${ext.slice(1)}` })
    formData.append('image', blob, path.basename(filePath))
    formData.append('overwrite', 'true')

    const res = await this.rawRequest('POST', '/upload/image', formData)
    if (!res.ok) {
      throw new Error(`Image upload failed: ${res.status} ${await res.text()}`)
    }

    const json: UploadResult = await res.json()
    // ComfyUI returns { name, subfolder, type }
    return json
  }

  /** Download an output file from ComfyUI's output directory */
  async downloadOutput(nodeId: number, filename: string, subfolder?: string): Promise<Buffer> {
    const params = new URLSearchParams({ filename, type: 'output', subfolder: subfolder || '' })
    const res = await this.rawRequest('GET', `/view?${params}`)
    if (!res.ok) {
      throw new Error(`Failed to download output: ${res.status}`)
    }
    return Buffer.from(await res.arrayBuffer())
  }

  /** Free GPU memory — call before model switch */
  async freeMemory(): Promise<void> {
    try {
      await this.request('POST', '/free', { unload_models: true, free_memory: true })
    } catch {
      // freeMemory is best-effort
    }
  }

  // ─── Status ───────────────────────────────────────────────

  /** Health check — returns true if ComfyUI is reachable */
  async healthCheck(): Promise<boolean> {
    try {
      await this.request<SystemStatsResponse>('GET', '/system_stats')
      return true
    } catch {
      return false
    }
  }

  /** Current queue state */
  async getQueue(): Promise<QueueStatus> {
    const data = await this.request<{ queue_running: unknown[]; queue_pending: unknown[] }>('GET', '/queue')
    return {
      running: data.queue_running.length,
      pending: data.queue_pending.length,
    }
  }

  // ─── Internal HTTP ────────────────────────────────────────

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const url = `${this.baseUrl}${path}`

    const headers: Record<string, string> = {}
    if (body && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json'
    }

    let lastErr: Error | undefined
    for (let attempt = 0; attempt < this.maxRetries; attempt++) {
      try {
        const res = await fetch(url, {
          method,
          headers,
          body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
          signal: AbortSignal.timeout(10_000),
        })

        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(`ComfyUI ${method} ${path}: ${res.status} ${text}`)
        }

        return await res.json() as T
      } catch (err) {
        lastErr = err instanceof Error ? err : new Error(String(err))
        if (attempt < this.maxRetries - 1) {
          await sleep(500 * Math.pow(2, attempt)) // exponential backoff
        }
      }
    }

    throw new ComfyUIConnectionError(this.baseUrl, lastErr)
  }

  private async rawRequest(method: string, path: string, body?: BodyInit): Promise<Response> {
    const url = `${this.baseUrl}${path}`
    return fetch(url, { method, body })
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}