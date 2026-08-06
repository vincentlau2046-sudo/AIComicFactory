# Provider 接口兼容性审计（Provider Interface Audit）

> 项目：AIComicBuilder（Next.js 16）
> 审计范围：`src/lib/ai/providers/`（9 个 Provider）+ `src/lib/ai/types.ts`（接口契约）
> 方法：逐文件核对 `list_symbols` 方法清单 + `read_symbol` 读取关键方法体
> 只读分析，未修改任何源码

---

## 1. 接口契约对齐

### 1.1 契约定义（`src/lib/ai/types.ts`）

```ts
// types.ts:19-22
export interface AIProvider {
  generateText(prompt: string, options?: TextOptions): Promise<string>;
  generateImage(prompt: string, options?: ImageOptions): Promise<string>;
}

// types.ts:51-52
export interface VideoProvider {
  generateVideo(params: VideoGenerateParams): Promise<VideoGenerateResult>;
}
```

### 1.2 AIProvider 实现审计

| Provider | 文件 | 声明 | `generateText` | `generateImage` | 签名一致 |
|---|---|---|---|---|---|
| `OpenAIProvider` | `providers/openai.ts:7` | `implements AIProvider` | `(prompt: string, options?: TextOptions)` ✓ | `(prompt: string, options?: ImageOptions)` ✓ | ✅ 严格一致 |
| `GeminiProvider` | `providers/gemini.ts:7` | `implements AIProvider` | `(prompt: string, options?: TextOptions)` ✓ | `(prompt: string, options?: ImageOptions)` ✓ | ✅ 严格一致 |
| `DashScopeImageProvider` | `providers/dashscope-image.ts:94` | `implements AIProvider` | 签名一致，但**实现为抛错占位** | ✓ | ⚠️ 签名一致 / 功能不完整 |
| `KlingImageProvider` | `providers/kling-image.ts:35` | `implements AIProvider` | 签名一致，但**实现为抛错占位** | ✓ | ⚠️ 签名一致 / 功能不完整 |

占位实现代码引用：

```ts
// dashscope-image.ts:119-124
async generateText(
  _prompt: string,
  _options?: TextOptions,
): Promise<string> {
  throw new Error("DashScope image models do not support text generation");
}

// kling-image.ts:63-65
async generateText(_prompt: string, _options?: TextOptions): Promise<string> {
  throw new Error("Kling does not support text generation");
}
```

> 说明：四个 AIProvider 的**方法签名全部严格遵循契约**（无参数增减、无返回类型偏差），但 DashScope 与 Kling 的 `generateText` 是「签名合规、功能占位」——调用即抛错。契约本身未区分「文本能力」与「图像能力」，是类型系统层面允许、运行时层面的能力缺口。

### 1.3 VideoProvider 实现审计

| Provider | 文件 | 声明 | `generateVideo` | 签名一致 |
|---|---|---|---|---|
| `KlingVideoProvider` | `providers/kling-video.ts:59` | `implements VideoProvider` | `(params: VideoGenerateParams): Promise<VideoGenerateResult>` ✓ | ✅ 严格一致 |
| `SeedanceProvider` | `providers/seedance.ts:28` | `implements VideoProvider` | ✓ | ✅ 严格一致 |
| `UCloudSeedanceProvider` | `providers/ucloud-seedance.ts:37` | `implements VideoProvider` | ✓ | ✅ 严格一致 |
| `VeoProvider` | `providers/veo.ts:31` | `implements VideoProvider` | ✓ | ✅ 严格一致 |
| `WanVideoProvider` | `providers/wan-video.ts:42` | `implements VideoProvider` | ✓ | ✅ 严格一致 |

> 全部 5 个 VideoProvider 均严格遵循 `generateVideo` 契约，无异常。

### 1.4 额外方法（私有扩展）审计

所有 Provider 的额外方法**均为 `private`**，未暴露任何公共扩展方法：

| Provider | 私有扩展方法 |
|---|---|
| `OpenAIProvider` | —（无额外方法，最纯净） |
| `GeminiProvider` | —（无额外方法） |
| `DashScopeImageProvider` | — |
| `KlingImageProvider` | `getAuthHeader()`、`pollForResult()` |
| `KlingVideoProvider` | `getAuthHeader()`、`mapDuration()`、`pollForResult()` |
| `SeedanceProvider` | `buildKeyframeBody()`、`buildReferenceBody()`、`pollForResult()` |
| `UCloudSeedanceProvider` | `buildKeyframeBody()`、`buildReferenceBody()`、`pollForResult()` |
| `VeoProvider` | `isVeo31()`、`generateWithReferenceImages()`、`finishGeneration()`、`pollForResult()` |
| `WanVideoProvider` | `isWan27()`（getter）、`buildKeyframeBody()`、`buildReferenceBody()`、`buildTextBody()`、`pollForResult()` |

> 结论：**没有任何 Provider 实现接口之外的可被外部调用的公共方法**，插件边界干净。额外的私有方法均服务于各厂商特有的鉴权（`getAuthHeader`）、轮询（`pollForResult`）与请求体构造（`build*`），属于实现细节。

---

## 2. 参数兼容性

### 2.1 `ImageOptions.referenceImages` / `referenceLabels`

契约定义（`types.ts:14-16`）：`referenceImages?: string[]`、`referenceLabels?: string[]`（"Must match referenceImages order"）。

| Provider | `referenceImages` | `referenceLabels` | 实现方式 |
|---|---|---|---|
| `GeminiProvider` | ✅ | ✅ | 逐图读取并注入 prompt 前缀标签 |
| `OpenAIProvider` | ❌ | ❌ | 不消费，`generateImage` 仅透传 size/aspectRatio/quality/model |
| `DashScopeImageProvider` | ❌ | ❌ | 不消费，仅处理 model/size 族系 |
| `KlingImageProvider` | ❌ | ❌ | 不消费，仅处理 aspectRatio |

唯一支持方代码引用（`gemini.ts:66-80`）：

```ts
if (options?.referenceImages?.length) {
  // 每张参考图转为 image_url part，并用 referenceLabels 生成 "[Character Reference: xxx]" 前缀
  const label = options.referenceLabels?.[ri]
    ? `[Character Reference: ${options.referenceLabels[ri]}]`
    : ...
}
```

**结论：`referenceImages` / `referenceLabels` 仅 `GeminiProvider` 一个实现真正消费**，其余 3 个图像 Provider 静默忽略该参数（类型上允许、运行时无效果）。

### 2.2 `TextOptions.images`（vision 输入）

契约定义（`types.ts:6`）：`images?: string[]`（"local file paths for vision input"）。

| Provider | 支持 | 说明 |
|---|---|---|
| `GeminiProvider` | ✅ | `generateText` 内逐图转 `Part` 附加到多模态请求（`gemini.ts:32-38`） |
| `OpenAIProvider` | ✅ | `generateText` 内将图像并入 messages content parts（`openai.ts:27-37`） |
| `DashScopeImageProvider` | ❌ | `generateText` 直接抛错，无 vision 路径 |
| `KlingImageProvider` | ❌ | `generateText` 直接抛错，无 vision 路径 |

代码引用（`openai.ts:27-37`）：

```ts
if (options?.images?.length) {
  // 本地路径转 base64 data URL，作为 content part 追加到 messages
}
```

**结论：vision 文本输入仅 OpenAI / Gemini 支持**，且两者实现方式一致（本地路径 → base64 内联），协议差异小。

### 2.3 `VideoGenerateParams.referenceImages`（角色一致性参考图）

契约定义（`types.ts:42-43`）：`referenceImages?: string[]`（"Character/style reference images for consistency"）。

| Provider | 支持 | 实现方式 / 约束 |
|---|---|---|
| `SeedanceProvider` | ✅ | Seedance 2.0 multi-reference：initialImage + referenceImages 全部以 `reference_image` role 提交，上限 8 张（`seedance.ts:120-135`） |
| `UCloudSeedanceProvider` | ✅ | 同 Seedance 语义，上限 8 张（`ucloud-seedance.ts:142-156`） |
| `WanVideoProvider` | ✅ | 仅 wan2.7（`isWan27`）走 `media[] reference_image`，上限 8 张（`wan-video.ts:185-200`） |
| `VeoProvider` | ✅ | 仅 Veo 3.1 + reference 模式：initialImage + referenceImages 合并进 `config.referenceImages`，上限 3 张（`veo.ts:59-66, 108-138`） |
| `KlingVideoProvider` | ❌ | 完全不消费，仅支持 firstFrame/lastFrame 关键帧模式 |

代码引用（`veo.ts:116-126`）：

```ts
const allRefPaths = [initialImage, ...(params.referenceImages ?? [])].slice(0, 3);
const referenceImages = allRefPaths.map((imgPath) => ({...}));
// referenceImages requires duration=8
config.referenceImages = referenceImages;
```

**结论：4/5 视频 Provider 支持 `referenceImages`，但语义约束各不相同**（数量上限 3 vs 8、依赖特定模型版本、要求 reference 模式），`KlingVideoProvider` 完全不支持。

---

## 3. IFF 适配建议（假设 IFF Proxy 走 OpenAI-compatible 协议）

### 3.1 `OpenAIProvider` 可直接覆盖的能力

| 能力 | 覆盖情况 | 依据 |
|---|---|---|
| 文本生成（含 systemPrompt / temperature / maxTokens） | ✅ 完整覆盖 | `openai.ts:21-53` |
| Vision 输入（`TextOptions.images`） | ✅ 完整覆盖 | `openai.ts:27-37` |
| 图像生成（DALL-E 与 OpenAI-compatible 非 DALL-E 双分支） | ✅ 完整覆盖 | `openai.ts:55-93`：`compatParams` 透传 `size` / `aspect_ratio`，适配 seedream、doubao 等兼容 API |
| 图像生成参数（size / aspectRatio / quality / model） | ✅ 完整覆盖 | 同上 |
| 视频生成 | ❌ **不覆盖** | `OpenAIProvider` 未实现 `generateVideo`，契约中无视频方法 |

### 3.2 需要额外适配的点

**① Vision reference image 传递（图像 → 文本的参考图）**
- 现状：`OpenAIProvider.generateText` 的 `images` 走 base64 内联 content parts，天然支持 OpenAI-compatible 协议，IFF 侧**无需改造**即可透传 `TextOptions.images`。
- 注意：参考图语义（"角色参考"而非"视觉问答输入"）在 `TextOptions` 中无区分字段——若 IFF 需要区分，建议在协议层通过 systemPrompt 注入角色说明，或在 `TextOptions` 增加语义字段（属接口演进，不在本次审计范围）。

**② 图像生成 referenceImages（`ImageOptions.referenceImages/referenceLabels`）**
- 现状：仅 Gemini 消费；`OpenAIProvider.generateImage` **静默忽略**该参数。
- 适配选项：
  - **方案 A（推荐）**：扩展 `OpenAIProvider.generateImage`，将 referenceImages 以 data URL 追加进 prompt 或请求体（DALL-E 3 原生不支持参考图，但 OpenAI-compatible 的 IFF 端点可在兼容参数中透传 `reference_images`）。
  - 方案 B：参考 Gemini 的标签注入模式（`gemini.ts:66-80`），在 prompt 中拼接 `[Character Reference: <label>]` 描述，零协议改动、兼容性最好但效果依赖模型。

**③ 视频模式差异（`VideoGenerateParams` 的三种形态）**
- `VideoGenerateParams` 是判别联合（`KeyframeVideoParams` | `ReferenceVideoParams`），`OpenAIProvider` 无任何视频能力，IFF 视频接入需要**新建一个 `implements VideoProvider` 的 OpenAI-compatible 视频 Provider**（或在 IFF 侧提供独立视频端点）。
- 需映射的差异点：
  - **关键帧模式**（`firstFrame` + `lastFrame`）：对应 OpenAI-compatible 视频 API 的 image-to-video（如 Sora / IFF 私有端点）；
  - **参考图模式**（`initialImage` + `referenceImages`）：对应 multi-reference 语义——参考 Seedance/UCloud 的 `reference_image` role 模式（上限 8）或 Veo 3.1 的 `config.referenceImages`（上限 3），需在 IFF 协议中明确数量上限与顺序约定（`referenceLabels` 对齐 `referenceImages` 序）；
  - **duration / ratio**：各厂商约束不同（Veo 固定 8s、Kling `mapDuration` 取整），IFF 侧需在边界层 clamp/校验，避免下沉到 Provider。
- 轮询语义：所有视频 Provider 均为「提交任务 → 轮询结果」（`pollForResult`），IFF 若为同步返回视频 URL 的端点，可直接复用；若为异步任务端点，需实现对应轮询器。

**④ 文本能力缺口（路由层面）**
- `DashScopeImageProvider` / `KlingImageProvider` 的 `generateText` 抛错。若 IFF 统一走 OpenAI-compatible，应**将文本类任务（如 `script-outline`、`script-parse` 等 pipeline 步骤）路由到 OpenAI-compatible 文本端点**，避免落到纯图像 Provider 上直接抛错。

---

## 4. 结论摘要

1. **签名层面 9/9 Provider 全部严格遵循契约**；`DashScopeImageProvider`、`KlingImageProvider` 的 `generateText` 是签名合规但运行时抛错的占位实现。
2. **无公共扩展方法**，所有厂商私有实现（鉴权/轮询/请求体构造）均 `private`，插件边界干净。
3. **参数支持高度不均衡**：`referenceImages` 在图像侧仅 Gemini 支持、在视频侧 4/5 支持但约束各异（数量、版本、模式）；vision 输入仅 OpenAI/Gemini 支持。
4. **IFF 适配主路径清晰**：OpenAI-compatible 协议下，文本 + vision + 图像能力可被 `OpenAIProvider` 直接覆盖；**唯一硬缺口是视频生成**（需新 Provider），另需决策图像 referenceImages 的透传方案（推荐方案 A：扩展 OpenAIProvider 兼容参数）。
