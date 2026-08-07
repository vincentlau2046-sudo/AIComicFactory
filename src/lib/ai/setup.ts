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

  // ─── Composite mode: IFF text/VL + ComfyUI image ─────────
  if (iffConfigured && comfyConfigured) {
    const textProvider = new OpenAIProvider()
    const imageProvider = createComfyUIProvider()

    setDefaultAIProvider(
      new CompositeAIProvider(textProvider, imageProvider,
        (u) => new OpenAIProvider({ ...(u && { uploadDir: u }) }),
        (u) => createComfyUIProvider(),
      ),
      CompositeAIProvider.createFactory(
        textProvider, imageProvider,
        (u) => new OpenAIProvider({ ...(u && { uploadDir: u }) }),
        (u) => createComfyUIProvider(),
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