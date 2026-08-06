import type { TextOptions } from "@/lib/ai/types";

interface ContinuityResult {
  pass: boolean;
  issues: string[];
}

const CONTINUITY_PROMPT = `比较这两帧来自动画影片的连续画面。
第一帧是上一个镜头的末帧。
第二帧是下一个镜头的首帧。

检查连续性问题：
1. 角色服装一致性（相同的服装、配饰、发型）
2. 角色位置逻辑延续性（自然的运动过渡）
3. 光照方向一致性（相同的光源角度）
4. 色调一致性（匹配的调色）
5. 背景连续性（如果是同一地点）

仅输出有效 JSON（不使用 markdown）：
{"pass": true/false, "issues": ["每个发现的问题描述"]}

如果没有显著的连续性断裂则通过。不同机位角度带来的轻微透视变化是正常的、预期的。`;

export async function checkContinuity(
  provider: { generateText: (prompt: string, options?: TextOptions) => Promise<string> },
  lastFrameUrl: string,
  nextFirstFrameUrl: string
): Promise<ContinuityResult> {
  try {
    const result = await provider.generateText(CONTINUITY_PROMPT, {
      images: [lastFrameUrl, nextFirstFrameUrl],
    });

    const jsonMatch = result.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return { pass: true, issues: [] };

    const parsed = JSON.parse(jsonMatch[0]);
    return {
      pass: parsed.pass ?? true,
      issues: parsed.issues ?? [],
    };
  } catch {
    // If continuity check itself fails, default to pass (don't block generation)
    return { pass: true, issues: [] };
  }
}
