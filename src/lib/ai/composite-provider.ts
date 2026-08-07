/**
 * CompositeAIProvider — routes text/image generation to different backends.
 *
 * Route table:
 *   generateText() without images  → textProvider (→ IFF proxy, deepseek-v4-flash)
 *   generateText() with images     → vlProvider   (→ vLLM, qwen3-vl-4b)
 *   generateImage()                → imageProvider (→ ComfyUI, local)
 *
 * VL provider is optional — system degrades gracefully when not configured.
 */

import type { AIProvider, ImageOptions, TextOptions } from './types'

export class CompositeAIProvider implements AIProvider {
  constructor(
    private textProvider: AIProvider,
    private imageProvider: AIProvider,
    private vlProvider?: AIProvider,
    private textFactory?: (uploadDir?: string) => AIProvider,
    private imageFactory?: (uploadDir?: string) => AIProvider,
    private vlFactory?: (uploadDir?: string) => AIProvider,
  ) {}

  async generateText(prompt: string, options?: TextOptions): Promise<string> {
    // VL routing: when images are provided, use the VL provider
    if (options?.images?.length && this.vlProvider) {
      return this.vlProvider.generateText(prompt, {
        ...options,
        model: options.model || process.env.OPENAI_VL_MODEL || 'qwen3-vl-4b',
      })
    }

    // Pure text: use the text provider (IFF proxy → deepseek-v4-flash)
    return this.textProvider.generateText(prompt, options)
  }

  async generateImage(prompt: string, options?: ImageOptions): Promise<string> {
    return this.imageProvider.generateImage(prompt, options)
  }

  /**
   * Creates a factory function for setDefaultAIProvider.
   * When uploadDir is provided, creates fresh instances with the upload dir.
   */
  static createFactory(
    textProvider: AIProvider,
    imageProvider: AIProvider,
    textFactory: (uploadDir?: string) => AIProvider,
    imageFactory: (uploadDir?: string) => AIProvider,
    vlProvider?: AIProvider,
    vlFactory?: (uploadDir?: string) => AIProvider,
  ): (uploadDir?: string) => CompositeAIProvider {
    return (uploadDir?: string) => {
      if (!uploadDir) return new CompositeAIProvider(textProvider, imageProvider, vlProvider, textFactory, imageFactory, vlFactory)
      return new CompositeAIProvider(
        textFactory(uploadDir),
        imageFactory(uploadDir),
        vlFactory?.(uploadDir),
        textFactory,
        imageFactory,
        vlFactory,
      )
    }
  }
}