import { setDefaultAIProvider, setDefaultVideoProvider } from "./index";
import { OpenAIProvider } from "./providers/openai";
import { GeminiProvider } from "./providers/gemini";
import { SeedanceProvider } from "./providers/seedance";
import { ComfyUIProvider } from "@/lib/comfyui";

let initialized = false;

function createComfyUIProvider(): ComfyUIProvider {
  return new ComfyUIProvider({
    baseUrl: process.env.COMFYUI_BASE_URL || "http://localhost:8188",
    workflowsDir: process.env.COMFYUI_WORKFLOWS_DIR || "/home/vince/ComfyUI/workflows/AIComicFactory/atomic",
    outputDir: process.env.OUTPUT_DIR || undefined,
    pipelinesDir: process.env.COMFYUI_PIPELINES_DIR,
  });
}

export function initializeProviders() {
  if (initialized) return;

  // Text/image: OpenAI-compatible (IFF Proxy) or Gemini
  // This provider handles both generateText() and generateImage()
  if (process.env.OPENAI_API_KEY) {
    setDefaultAIProvider(
      new OpenAIProvider(),
      (uploadDir) => new OpenAIProvider({ ...(uploadDir && { uploadDir }) }),
    );
  } else if (process.env.GEMINI_API_KEY) {
    setDefaultAIProvider(
      new GeminiProvider(),
      (uploadDir) => new GeminiProvider({ ...(uploadDir && { uploadDir }) }),
    );
  }

  // Image/video: ComfyUI local provider
  // NOTE: ComfyUI does NOT support generateText() — only register it as
  // AIProvider if no text provider was set above. Otherwise, use it only
  // for video generation. Image generation via ComfyUI is accessed through
  // PipelineEngine (internal to ComfyUIProvider), not through the default AIProvider.
  const comfyConfigured = !!(process.env.COMFYUI_BASE_URL || process.env.COMFYUI_WORKFLOWS_DIR)
  if (comfyConfigured) {
    // Only set as AI provider if no text provider was configured
    // (otherwise ComfyUI's generateText() would throw)
    if (!process.env.OPENAI_API_KEY && !process.env.GEMINI_API_KEY) {
      setDefaultAIProvider(
        createComfyUIProvider(),
        (_uploadDir) => createComfyUIProvider(),
      );
    }
  }

  // Video generation
  if (process.env.SEEDANCE_API_KEY) {
    setDefaultVideoProvider(
      new SeedanceProvider(),
      (uploadDir) => new SeedanceProvider({ ...(uploadDir && { uploadDir }) }),
    );
  }

  // ComfyUI also serves as video provider if configured
  if (comfyConfigured && !process.env.SEEDANCE_API_KEY) {
    setDefaultVideoProvider(
      createComfyUIProvider(),
      (_uploadDir) => createComfyUIProvider(),
    );
  }

  initialized = true;
}
