import { classifyModelFamily, type ModelFamily } from './types'

/**
 * Tracks which GPU model is currently loaded and decides when to free memory.
 *
 * Model families that can share VRAM:
 *   qwen-image: Qwen 2512 T2I / 2511 Edit / 2511 Edit Plus / 2511 MultiAngle
 *   minimax-h3: H3 T2V / I2V / R2V
 *   cpu: no GPU needed
 *
 * Cross-family transitions trigger freeMemory().
 * Within-family transitions skip it (models share VRAM).
 */
export class GPUScheduler {
  private currentFamily: ModelFamily | null = null
  private readonly freeFn: (() => Promise<void>) | null

  constructor(freeFn?: () => Promise<void>) {
    this.freeFn = freeFn ?? null
  }

  /**
   * Called before each step. Returns the model family to use.
   * If the family changed from the previous step, calls freeFn (if provided).
   */
  async onStepTransition(metaGpuModel?: string): Promise<ModelFamily> {
    const nextFamily = classifyModelFamily(metaGpuModel)

    if (this.currentFamily && this.currentFamily !== nextFamily) {
      // Cross-family transition — need to free GPU memory
      // This includes 'unknown' → any other family (fail-safe)
      if (this.freeFn) {
        try {
          await this.freeFn()
        } catch (err) {
          console.warn(`[GPUScheduler] freeMemory() failed during transition: ${err}`)
        }
      }
    }

    this.currentFamily = nextFamily
    return nextFamily
  }

  /**
   * Force-free at the end of a pipeline.
   */
  async finalize(): Promise<void> {
    if (this.currentFamily && this.currentFamily !== 'cpu' && this.freeFn) {
      try {
        await this.freeFn()
      } catch (err) {
        console.warn(`[GPUScheduler] freeMemory() failed during finalize: ${err}`)
      }
    }
    this.currentFamily = null
  }

  getCurrentFamily(): ModelFamily | null {
    return this.currentFamily
  }
}