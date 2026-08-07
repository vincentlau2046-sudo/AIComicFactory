/**
 * CompositeAIProvider — routes text/image generation to different backends.
 *
 * Route table:
 *   generateText() without images  → textProvider (→ IFF :8999, deepseek-v4-flash)
 *   generateText() with images     → textProvider (→ IFF :8999, qwen3-vl-4b)
 *   generateImage()                → imageProvider (→ ComfyUI :8188)
 *
 * Both text routes go through IFF proxy — only the model name differs.
 * IFF handles backend routing based on model name.
 */

import type { AIProvider, ImageOptions, TextOptions } from './types'

const VL_MODEL = process.env.OPENAI_VL_MODEL || 'qwen3-vl-4b'
const TEXT_MODEL = process.env.OPENAI_MODEL || 'deepseek-v4-flash'

export class CompositeAIProvider implements AIProvider {
  constructor(
    private textProvider: AIProvider,
    private imageProvider: AIProvider,
    private factory: (uploadDir?: string) => AIProvider,
    private imageFactory: (uploadDir?: string) => AIProvider,
  ) {}

  async generateText(prompt: string, options?: TextOptions): Promise<string> {
    // When images provided, switch to VL model (IFF routes to correct backend)
    // Both go through the same IFF proxy — just the model changes
    if (options?.images?.length) {
      return this.textProvider.generateText(prompt, {
        ...options,
        model: options.model || VL_MODEL,
      })
    }
    // Pure text: default model (deepseek-v4-flash)
    return this.textProvider.generateText(prompt, options)
  }

  async generateImage(prompt: string, options?: ImageOptions): Promise<string> {
    return this.imageProvider.generateImage(prompt, options)
  }

  /** Factory for setDefaultAIProvider — creates fresh CompositeAIProvider with upload dir support */
  static createFactory(
    textProvider: AIProvider,
    imageProvider: AIProvider,
    textFactory: (uploadDir?: string) => AIProvider,
    imageFactory: (uploadDir?: string) => AIProvider,
  ): (uploadDir?: string) => CompositeAIProvider {
    return (uploadDir?: string) => {
      if (!uploadDir) return new CompositeAIProvider(textProvider, imageProvider, textFactory, imageFactory)
      return new CompositeAIProvider(
        textFactory(uploadDir),
        imageFactory(uploadDir),
        textFactory,
        imageFactory,
      )
    }
  }
}