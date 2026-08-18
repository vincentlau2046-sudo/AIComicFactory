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
  /** Total timeout for reconnection attempts (ms, default: 60000 = 60s) */
  reconnectTimeout?: number
}

const DEFAULTS = {
  baseUrl: 'http://localhost:8188',
  defaultTimeout: 900_000, // 15 min per video
  pollInterval: 500,
  maxRetries: 3,
  reconnectTimeout: 60_000, // 60s
}

export class ComfyUIClient {
  private baseUrl: string
  private defaultTimeout: number
  private pollInterval: number
  private maxRetries: number
  private reconnectTimeout: number

  /** Track connection health state */
  private isHealthy: boolean = true
  private reconnecting: boolean = false
  private healthCheckInFlight: Promise<boolean> | null = null

  constructor(opts?: ClientOptions) {
    this.baseUrl = (opts?.baseUrl || DEFAULTS.baseUrl).replace(/\/+$/, '')
    this.defaultTimeout = opts?.defaultTimeout ?? DEFAULTS.defaultTimeout
    this.pollInterval = opts?.pollInterval ?? DEFAULTS.pollInterval
    this.maxRetries = opts?.maxRetries ?? DEFAULTS.maxRetries
    this.reconnectTimeout = opts?.reconnectTimeout ?? DEFAULTS.reconnectTimeout
  }

  /**
   * Ensure ComfyUI is connected and healthy.
   * Returns true if healthy, false if not reachable.
   * Caches concurrent calls to avoid duplicate health checks.
   */
  async ensureConnected(): Promise<boolean> {
    if (this.isHealthy) return true
    return this.reconnect()
  }

  /**
   * Attempt to reconnect to ComfyUI with backoff.
   * Sets isHealthy based on success.
   */
  async reconnect(): Promise<boolean> {
    // Deduplicate concurrent reconnect attempts
    if (this.reconnecting && this.healthCheckInFlight) {
      return this.healthCheckInFlight
    }

    this.reconnecting = true
    this.healthCheckInFlight = this._doReconnect()

    try {
      const result = await this.healthCheckInFlight
      return result
    } finally {
      this.reconnecting = false
      this.healthCheckInFlight = null
    }
  }

  private async _doReconnect(): Promise<boolean> {
    const deadline = Date.now() + this.reconnectTimeout
    let attempt = 0

    while (Date.now() < deadline) {
      attempt++
      try {
        const ok = await this.healthCheck()
        if (ok) {
          this.isHealthy = true
          console.log(`[ComfyUIClient] Reconnected after ${attempt} attempt(s)`)
          return true
        }
      } catch {
        // Connection failed, will retry
      }

      const remaining = deadline - Date.now()
      if (remaining <= 0) break

      // Exponential backoff with jitter (max 5s per wait)
      const delay = Math.min(500 * Math.pow(2, attempt - 1), 5000)
      const jittered = Math.round(delay * (0.75 + Math.random() * 0.5))
      await sleep(Math.min(jittered, remaining))
    }

    this.isHealthy = false
    console.error(`[ComfyUIClient] Reconnection failed after timeout (${this.reconnectTimeout}ms)`)
    return false
  }

  // ─── Core API ─────────────────────────────────────────────

  /** Submit a workflow and return the prompt_id */
  async submit(workflow: object): Promise<string> {
    // Pre-execution health check
    const connected = await this.ensureConnected()
    if (!connected) {
      throw new ComfyUIConnectionError(
        this.baseUrl,
        new Error('ComfyUI is not reachable — cannot submit workflow')
      )
    }

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
      // If we know we're disconnected, attempt reconnect before polling
      if (!this.isHealthy) {
        const reconnected = await this.reconnect()
        if (!reconnected) {
          throw new ComfyUIConnectionError(
            this.baseUrl,
            new Error('Connection lost during poll — reconnection failed')
          )
        }
      }

      let data: HistoryResponse
      try {
        data = await this.request<HistoryResponse>('GET', `/history/${promptId}`)
      } catch (err) {
        // If request fails due to connection, mark unhealthy and continue loop
        if (err instanceof ComfyUIConnectionError) {
          this.isHealthy = false
          await sleep(interval)
          continue
        }
        throw err
      }

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
  async uploadImage(filePath: string, options?: { uniqueName?: string }): Promise<UploadResult> {
    if (!fs.existsSync(filePath)) {
      throw new Error(`Image file not found: ${filePath}`)
    }

    const ext = path.extname(filePath).toLowerCase()
    const supportedExts = ['.png', '.jpg', '.jpeg', '.webp', '.bmp']
    if (!supportedExts.includes(ext)) {
      throw new Error(`Unsupported image format: ${ext}. Supported: ${supportedExts.join(', ')}`)
    }

    // Use unique name to avoid collisions when multiple files share the same basename
    const baseName = path.basename(filePath)
    const uploadName = options?.uniqueName
      ? `${options.uniqueName}_${baseName}`
      : baseName

    const formData = new FormData()
    const blob = new Blob([fs.readFileSync(filePath)], { type: `image/${ext.slice(1)}` })
    formData.append('image', blob, uploadName)
    formData.append('overwrite', 'true')

    const res = await this.rawRequest('POST', '/upload/image', formData)
    if (!res.ok) {
      throw new Error(`Image upload failed: ${res.status} ${await res.text()}`)
    }

    const json: UploadResult = await res.json()
    // ComfyUI returns { name, subfolder, type }
    return json
  }

  /** Download an output file from ComfyUI's output directory with retry. */
  async downloadOutput(nodeId: number, filename: string, subfolder?: string): Promise<Buffer> {
    const params = new URLSearchParams({ filename, type: 'output', subfolder: subfolder || '' })
    const deadline = Date.now() + 60_000; // 60s total deadline
    let lastErr: Error | undefined;

    for (let attempt = 0; attempt < 4; attempt++) {
      if (Date.now() >= deadline) {
        throw new Error(`Download deadline exceeded for ${filename}`);
      }
      try {
        const res = await this.rawRequest('GET', `/view?${params}`, undefined, { timeout: 30_000 });
        if (!res.ok) {
          // 404: ComfyUI file not ready yet (race condition) — retry once
          if (res.status === 404 && attempt < 1) {
            lastErr = new Error(`Download 404 (retryable): ${filename}`);
            await sleep(1000);
            continue;
          }
          if (res.status === 404) throw new Error(`Download 404 (permanent): ${filename}`);
          // 5xx / 502/503/504: retryable
          if (res.status >= 500 || [502, 503, 504].includes(res.status)) {
            lastErr = new Error(`Download HTTP ${res.status}: ${filename}`);
            if (attempt < 3) { await sleep(1000 * Math.pow(2, attempt) + Math.random() * 500); continue; }
            throw lastErr;
          }
          throw new Error(`Download HTTP ${res.status}: ${filename}`);
        }
        const buf = Buffer.from(await res.arrayBuffer());
        // Content-Length integrity check
        const contentLength = res.headers.get('content-length');
        if (contentLength && buf.length !== parseInt(contentLength, 10)) {
          lastErr = new Error(`Download truncated: expected ${contentLength}B, got ${buf.length}B`);
          if (attempt < 3) { await sleep(1000 * Math.pow(2, attempt) + Math.random() * 500); continue; }
          throw lastErr;
        }
        return buf;
      } catch (err) {
        lastErr = err instanceof Error ? err : new Error(String(err));
        // Connection/timeout errors: retry
        if (attempt < 3 && (lastErr.message.includes('fetch') || lastErr.message.includes('timeout') || lastErr.message.includes('abort'))) {
          console.warn(`[ComfyUI] Download retry ${attempt + 1}/4 for ${filename}: ${lastErr.message}`);
          await sleep(1000 * Math.pow(2, attempt) + Math.random() * 500);
          continue;
        }
        if (attempt < 3) throw lastErr; // non-retryable
      }
    }
    throw lastErr ?? new Error(`Download failed after 4 attempts: ${filename}`);
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

        // Successful request — mark as healthy
        this.isHealthy = true
        return await res.json() as T
      } catch (err) {
        lastErr = err instanceof Error ? err : new Error(String(err))

        // Detect connection errors and mark unhealthy
        if (this.isConnectionError(lastErr)) {
          this.isHealthy = false
          // Wrap in ComfyUIConnectionError and throw immediately — let caller decide reconnection
          throw new ComfyUIConnectionError(this.baseUrl, lastErr)
        }

        if (attempt < this.maxRetries - 1) {
          await sleep(500 * Math.pow(2, attempt)) // exponential backoff
        }
      }
    }

    throw lastErr ?? new Error(`ComfyUI request failed: ${method} ${path}`)
  }

  /**
   * Detect if an error is a connection-level issue (network, DNS, ECONNREFUSED, etc.)
   * vs. an application-level error.
   */
  private isConnectionError(err: Error): boolean {
    const msg = err.message.toLowerCase()
    return (
      msg.includes('fetch failed') ||
      msg.includes('econnrefused') ||
      msg.includes('econnreset') ||
      msg.includes('enotfound') ||
      msg.includes('etimedout') ||
      msg.includes('networkerror') ||
      msg.includes('abort') ||
      msg.includes('timeout') ||
      msg.includes('fetch is not defined') ||
      err.name === 'TypeError' && msg.includes('fetch') ||
      err.name === 'AbortError'
    )
  }

  private async rawRequest(method: string, path: string, body?: BodyInit, opts?: { timeout?: number }): Promise<Response> {
    const url = `${this.baseUrl}${path}`
    const init: RequestInit = { method, body };
    if (opts?.timeout) init.signal = AbortSignal.timeout(opts.timeout);
    return fetch(url, init);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}