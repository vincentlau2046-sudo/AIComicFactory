import { setDefaultAIProvider, setDefaultVideoProvider } from "./index";
import { OpenAIProvider } from "./providers/openai";
import { GeminiProvider } from "./providers/gemini";
import { SeedanceProvider } from "./providers/seedance";
import { ComfyUIProvider } from "@/lib/comfyui";
import { CompositeAIProvider } from "./composite-provider";

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

  // ─── Detect configured providers ────────────────────────
  const iffConfigured = !!(process.env.OPENAI_BASE_URL || process.env.OPENAI_API_KEY)
  const comfyConfigured = !!(process.env.COMFYUI_BASE_URL || process.env.COMFYUI_WORKFLOWS_DIR)
  const vlConfigured = !!(process.env.OPENAI_VL_BASE_URL)

  // ─── Composite mode: IFF text + ComfyUI image + vLLM VL ─
  if (iffConfigured && comfyConfigured) {
    const textProvider = new OpenAIProvider()
    const imageProvider = createComfyUIProvider()

    let vlProvider: OpenAIProvider | undefined
    if (vlConfigured) {
      vlProvider = new OpenAIProvider({
        baseURL: process.env.OPENAI_VL_BASE_URL,
        model: process.env.OPENAI_VL_MODEL || 'qwen3-vl-4b',
      })
    }

    setDefaultAIProvider(
      new CompositeAIProvider(textProvider, imageProvider, vlProvider,
        (u) => new OpenAIProvider({ ...(u && { uploadDir: u }) }),
        (u) => createComfyUIProvider(),
        vlConfigured ? (u) => new OpenAIProvider({
          baseURL: process.env.OPENAI_VL_BASE_URL,
          model: process.env.OPENAI_VL_MODEL || 'qwen3-vl-4b',
          ...(u && { uploadDir: u }),
        }) : undefined,
      ),
      CompositeAIProvider.createFactory(
        textProvider, imageProvider,
        (u) => new OpenAIProvider({ ...(u && { uploadDir: u }) }),
        (u) => createComfyUIProvider(),
        vlProvider,
        vlConfigured ? (u) => new OpenAIProvider({
          baseURL: process.env.OPENAI_VL_BASE_URL,
          model: process.env.OPENAI_VL_MODEL || 'qwen3-vl-4b',
          ...(u && { uploadDir: u }),
        }) : undefined,
      ),
    )
  }
  // ─── Legacy single-provider modes ───────────────────────
  else if (process.env.OPENAI_API_KEY) {
    // Text + image: both through IFF proxy (image gen may fail)
    setDefaultAIProvider(
      new OpenAIProvider(),
      (uploadDir) => new OpenAIProvider({ ...(uploadDir && { uploadDir }) }),
    );
  } else if (process.env.GEMINI_API_KEY) {
    setDefaultAIProvider(
      new GeminiProvider(),
      (uploadDir) => new GeminiProvider({ ...(uploadDir && { uploadDir }) }),
    );
  } else if (comfyConfigured) {
    // ComfyUI only (text will throw — image + video only)
    setDefaultAIProvider(
      createComfyUIProvider(),
      (_uploadDir) => createComfyUIProvider(),
    );
  }

  // ─── Video Provider ────────────────────────────────────
  if (process.env.SEEDANCE_API_KEY) {
    setDefaultVideoProvider(
      new SeedanceProvider(),
      (uploadDir) => new SeedanceProvider({ ...(uploadDir && { uploadDir }) }),
    );
  }

  // ComfyUI video: when configured and no cloud video API
  if (comfyConfigured && !process.env.SEEDANCE_API_KEY) {
    setDefaultVideoProvider(
      createComfyUIProvider(),
      (_uploadDir) => createComfyUIProvider(),
    );
  }

  initialized = true;
}