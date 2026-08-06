/**
 * User-side prompt builder for the keyframe (first/last frame) image-prompt
 * generation step. Mirrors `buildRefImagePromptsRequest` for the reference
 * mode pipeline. The system prompt lives in the registry under the
 * `shot_split_keyframe_assets` key.
 */

export function buildKeyframePromptsRequest(
  shots: Array<{
    sequence: number;
    prompt: string;
    motionScript?: string | null;
    cameraDirection?: string | null;
  }>,
  characters: Array<{
    name: string;
    description?: string | null;
    visualHint?: string | null;
  }>,
  visualStyle?: string
): string {
  const charDescriptions = characters
    .map(
      (c) =>
        `${c.name}（${c.visualHint || "无视觉标识"}）: ${c.description || ""}`
    )
    .join("\n");

  const shotDescriptions = shots
    .map(
      (s) =>
        `镜头 ${s.sequence}: ${s.prompt}${
          s.motionScript ? `\n动作: ${s.motionScript}` : ""
        }${s.cameraDirection ? `\n镜头运动: ${s.cameraDirection}` : ""}`
    )
    .join("\n\n");

  return `${visualStyle ? `视觉风格: ${visualStyle}\n\n` : ""}角色:\n${charDescriptions}\n\n分镜:\n${shotDescriptions}`;
}
