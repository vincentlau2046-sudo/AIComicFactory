# FL2V Content Layer 信息供给 — 详细实施方案

## 1. 角色列表：从全 EP → 按帧过滤

### 当前

```typescript
// video-generate.ts
const projectCharacters = await getEpisodeCharacters(projectId, shot.episodeId);
// → 5 个角色: 朱元璋, 刘德, 朱父, 朱母, 朱兄
```

传给 H3PromptInput 全量，即使 Shot 1 只有朱元璋出面。

### 修正

```typescript
// video-generate.ts — 在 getEpisodeCharacters 之后新增
import { stripCharHint } from "@/lib/shot-asset-utils";

// Extract frame-level character names from shot_assets
const ffChars = firstFrameAsset?.characters
  ? (typeof firstFrameAsset.characters === 'string'
      ? JSON.parse(firstFrameAsset.characters)
      : firstFrameAsset.characters)
  : [];
const lfChars = lastFrameAsset?.characters
  ? (typeof lastFrameAsset.characters === 'string'
      ? JSON.parse(lastFrameAsset.characters)
      : lastFrameAsset.characters)
  : [];
const frameCharNames = [...new Set([...ffChars, ...lfChars])];

// Filter to only characters present in the frames
const frameCharacters = projectCharacters.filter(c =>
  frameCharNames.some(n =>
    c.baseName === n || stripCharHint(c.name) === n
  )
);
// → 仅 1 个角色: 朱元璋
```

传给 H3PromptInput: `characters: frameCharacters`

### 数据库现状验证

Shot 1 的 first_frame v3：`characters = ["朱元璋"]`
Shot 1 的 last_frame v3：`characters = ["朱元璋"]`
→ 合并去重 = `["朱元璋"]` ✅

---

## 2. 剧集背景：从一行摘要 → EP 完整结构

### 当前

`episode.description` → `少年朱重八在贫困与灾荒中挣扎...` (46 字)

### 修正

在 `video-generate.ts` 中构建 EP 镜头结构文本：

```typescript
// Fetch all shots for this episode (same version)
const allEpisodeShots = await db.select()
  .from(shots)
  .where(and(
    eq(shots.episodeId, shot.episodeId),
    eq(shots.versionId, shot.versionId)
  ))
  .orderBy(asc(shots.sequence));

const episodeStructure = allEpisodeShots.length > 0
  ? [
      `本剧集共 ${allEpisodeShots.length} 个镜头。▶ 标记为当前正在处理的镜头：`,
      '',
      ...allEpisodeShots.map(s => {
        const isCurrent = s.id === shot.id;
        const marker = isCurrent ? '▶' : ' ';
        const desc = (s.prompt || s.sceneDescription || '').substring(0, 120);
        return `${marker} Shot ${s.sequence}: ${desc}`;
      })
    ].join('\n')
  : undefined;
```

然后传给 H3PromptInput:

```typescript
const h3Output = await buildH3Builder({
  // ... existing fields ...
  episodeDescription: episodeStructure || episode?.description,  // 优先用结构
  // episodeKeywords 保持不变
});
```

### 产出示例（EP01 的 12 个 shot）

```
本剧集共 12 个镜头。▶ 标记为当前正在处理的镜头：

  Shot 1: 内景. 渐次离世之屋, 连续半月。场景延续自朱家破屋，但光线随时间推移由明转暗...
  Shot 2: 朱家破屋。朱重八（皮包骨头放牛娃）跪在地上，双手撑地，低声啜泣...
▶ Shot 3: 焦黄色凤阳荒野。烈日中天，朱重八牵一头瘦骨嶙峋的黄牛行走于干裂土地...
  Shot 4: 朱家破屋。四人同框——朱父、朱母、朱兄卧病于地铺的草席之上...
  ...
```

**Token 预算**：12 shot × ~40 字 ≈ 500 字 ≈ 700 tokens。可接受。

### 备选：超长 EP（>20 shots）的处理

如果 EP 超过 20 个 shot，改为"邻居模式"：只传当前 shot 的前后各 2 个 + 其余 shot 的序号标题。

```typescript
if (allEpisodeShots.length > 20) {
  const currentIdx = allEpisodeShots.findIndex(s => s.id === shot.id);
  const neighbors = allEpisodeShots.slice(
    Math.max(0, currentIdx - 2),
    Math.min(allEpisodeShots.length, currentIdx + 3)
  );
  // Build: "Shot 1-8: (省略)... Shot 9: ... ▶ Shot 10: ... Shot 11: ... Shot 12-20: (省略)..."
}
```

---

## 3. 场景描述：新增 section

### 当前

`shot.prompt` 中没有被传给 Content Layer。P1 删除了 SCENE 段。

### 修正

在 Content Layer 中帧锚点之后，加"## 场景描述"段：

```typescript
// 在 buildContentLayer 的帧锚点段之后
if (input.sceneDescription) {
  parts.push(`## ${L("场景描述", "SCENE")}`);
  parts.push(input.sceneDescription);
  parts.push("");
}
```

### 数据来源

`video-generate.ts` 已加载 `sceneDesc`（来自 `shot.sceneId → scenes.description`）。

---

## 4. 帧锚点：恢复场景上下文

### 当前

`extractShotSubject` 只提取 `[shot] + [subject]`。

### 修正

扩展提取范围：`[shot] + [subject]/[scene] + [environment]`，仍然剥离 `[lighting]` 和 `[color]`（这两项由图片提供）。

```typescript
function extractFrameContet(prompt: string): string {
  // Changed from extractShotSubject
  const tags = ['shot', 'subject', 'scene', 'environment'];
  const parts: string[] = [];
  for (const tag of tags) {
    const m = prompt.match(new RegExp(`\\[${tag}\\]\[^\\\[]*`));
    if (m) parts.push(m[0].trim());
  }
  return parts.join(' | ') || prompt.slice(0, 100);
}
```

### 产出对比

```
Before: <Picture 1>: [shot] 全景，俯拍 | [subject] 朱元璋 站立...
After:  <Picture 1>: [shot] 全景，俯拍，35mm广角 | [subject] 朱元璋 站立... | [environment] 焦黄色凤阳荒野，干裂土层延伸至地平线，几棵枯树立在远处，热浪蒸腾
```

LLM 知道这是"荒野" → 可以设计"拉远突出孤寂"或"低角度地面蚂蚁"的过渡策略。

---

## 5. 镜头动作：motionScript 替代 videoScript

### 当前

Content 的"镜头意图"显示的是 `videoScript`（简洁概括）。

### 修正

改名为"镜头动作"，优先使用 `motionScript`（有时分段的详细版），无 motionScript 时退回 videoScript。

```typescript
const actionText = input.motionScript || input.videoScript;
const actionLabel = r("script_label", `## ${L("镜头动作", "SHOT ACTION")}`);
parts.push(actionLabel.replace("{{VIDEO_SCRIPT}}", actionText || "(no action)"));
```

同时更新注册表 `FL2V_CONTENT_SCRIPT_LABEL`：

```
## 镜头动作
以下是从首帧到尾帧之间应该发生的动作时间线。是你的"剧本"：
{{VIDEO_SCRIPT}}
```

---

## 6. 汇总：最终的 Content Layer

```
1. 帧锚点（含场景上下文）
   <Picture 1>: [shot] 全景，俯拍 | [subject] 朱元璋 站立... | [environment] 焦黄色荒野...
   <Picture 2>: [shot] 特写，仰视 | [subject] 朱元璋 蹲姿... | [environment] 焦黄色荒野...

2. 场景描述
   {shot.sceneDescription}

3. 镜头动作（时间线）
   {shot.motionScript}

4. 剧集全貌（▶ 当前镜头）
   本剧集共 12 个镜头...
     Shot 1: ...
   ▶ Shot 2: ...
     Shot 3: ...

5. 出场角色（仅本 shot 帧中的）
   - 朱元璋

6. 对话台本（可润色）
   (无)

7. 音频
   (none)

8. 旁白（已预生成，如适用）
```

---

## 7. 改动文件清单

| 文件 | 改动 |
|------|------|
| `video-generate.ts` | 帧角色过滤 + EP 结构生成 |
| `route.ts` (3 个视频 prompt 调用点) | 同 video-generate.ts |
| `prompt-template.ts` extractFrameContet | 扩展为+场景+环境 |
| `prompt-template.ts` buildContenLayer | 排序 + 场景+sections |
| `registry.ts` FL2V_CONTNET_SCRIPT_LABEL | "镜头动作"文案 |
| `types.ts` | 可选：新字段（不必，复用现字段） |