/**
 * TaskRetryStrategy — configurable retry with exponential backoff and jitter.
 *
 * Usage:
 *   const strategy = new RetryStrategy({ maxRetries: 3, baseDelay: 2000, jitter: true })
 *   const result = await strategy.execute(async () => await someTask())
 */

export interface RetryConfig {
  /** Maximum number of retry attempts (default: 3) */
  maxRetries?: number
  /** Base delay between retries in ms (default: 2000) */
  baseDelay?: number
  /** Maximum delay cap in ms (default: 30000) */
  maxDelay?: number
  /** Enable jitter to spread retry timing (default: true) */
  jitter?: boolean
  /** Error names to retry on. Empty = retry all errors (default: []) */
  retryableErrors?: string[]
  /** Callback on each retry attempt */
  onRetry?: (attempt: number, error: Error) => void
}

const DEFAULTS: Required<Omit<RetryConfig, 'onRetry'>> = {
  maxRetries: 3,
  baseDelay: 2000,
  maxDelay: 30000,
  jitter: true,
  retryableErrors: [],
}

export class RetryStrategy {
  private config: Required<Omit<RetryConfig, 'onRetry'>>
  private onRetry?: (attempt: number, error: Error) => void
  private _retryableErrors: string[] | undefined

  constructor(config: RetryConfig = {}) {
    this.config = { ...DEFAULTS, ...config }
    // Empty array = retry all → normalize to undefined for clean type
    this._retryableErrors = config.retryableErrors?.length === 0 ? undefined : config.retryableErrors
    this.onRetry = config.onRetry
  }

  /**
   * Execute an async function with retry logic.
   * Returns the result of the first successful invocation.
   * Throws the last error if all retries are exhausted.
   */
  async execute<T>(fn: () => Promise<T>): Promise<T> {
    const { maxRetries, baseDelay, maxDelay, jitter } = this.config
    const retryableErrors = this._retryableErrors

    let lastError: Error | undefined

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        return await fn()
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err))

        // Check if this error is retryable
        if (!RetryStrategy.isRetryable(lastError, retryableErrors)) {
          throw lastError
        }

        // Last attempt exhausted — rethrow
        if (attempt >= maxRetries) {
          throw lastError
        }

        // Notify callback
        if (this.onRetry) {
          try {
            this.onRetry(attempt + 1, lastError)
          } catch {
            // Callback errors should not disrupt retry logic
          }
        }

        // Calculate delay with exponential backoff
        const exponentialDelay = baseDelay * Math.pow(2, attempt)
        let delay = Math.min(exponentialDelay, maxDelay)

        // Apply jitter: randomize within ±25% of the delay
        if (jitter) {
          const jitterFactor = 0.75 + Math.random() * 0.5 // 0.75–1.25
          delay = Math.round(delay * jitterFactor)
        }

        await sleep(delay)
      }
    }

    // Should never reach here, but satisfy TypeScript
    throw lastError ?? new Error('RetryStrategy: unexpected termination')
  }

  /**
   * Determine if an error is retryable based on the configured error names.
   * When `retryableErrors` is undefined/null (meaning "all"), always retry.
   * When it's an empty array, always retry (set above to undefined).
   */
  static isRetryable(error: Error, retryableErrors?: string[]): boolean {
    // No filter = retry all
    if (!retryableErrors) return true
    // Empty filter = retry all (explicitly set to retry all)
    if (retryableErrors.length === 0) return true
    // Check by error name
    return retryableErrors.includes(error.name)
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}