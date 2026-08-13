import { NextResponse } from "next/server";
import { streamText, generateText } from "ai";
import { createLanguageModel, extractJSON } from "@/lib/ai/ai-sdk";
import { parseLLMJSON } from "@/lib/ai/json-repair";
import type { ProviderConfig } from "@/lib/ai/ai-sdk";
import { db } from "@/lib/db";
import { projects, episodes, characters, shots, dialogues, storyboardVersions, episodeCharacters, characterRelations, agentBindings, agents } from "@/lib/db/schema";
import { callAgent, callAgentStream, validateAgentOutput, type AgentCategory } from "@/lib/ai/agent-caller";

/** Wrap agent call + validation, returning user-friendly error response on failure */
async function callAndValidateAgent(
  agent: { platform: string; appId: string; apiKey: string },
  category: AgentCategory,
  prompt: string,
): Promise<{ text: string } | NextResponse> {
  try {
    const rawText = await callAgent(
      { platform: agent.platform as "bailian" | "dify" | "coze", appId: agent.appId, apiKey: agent.apiKey },
      prompt,
    );
    if (category !== "keyframe_prompts" && category !== "video_prompts") {
      validateAgentOutput(category, rawText);
    }
    return { text: rawText };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`[Agent ${category}] Error:`, message);
    return NextResponse.json({ error: message }, { status: 422 });
  }
}
import { eq, asc, and, lt, gt, desc, or, isNull, inArray } from "drizzle-orm";
import { getUserIdFromRequest } from "@/lib/get-user-id";
import path from "path";
import { id as genId } from "@/lib/id";
import { enqueueTask } from "@/lib/task-queue";
import type { TaskType } from "@/lib/task-queue";
import { buildScriptParsePrompt } from "@/lib/ai/prompts/script-parse";
import { buildScriptGeneratePrompt } from "@/lib/ai/prompts/script-generate";
import { buildCharacterExtractPrompt } from "@/lib/ai/prompts/character-extract";
import { buildShotSplitPrompt } from "@/lib/ai/prompts/shot-split";
import { resolvePrompt, resolveSlotContents } from "@/lib/ai/prompts/resolver";
import { getPromptDefinition } from "@/lib/ai/prompts/registry";
import { getModelMaxDuration } from "@/lib/ai/model-limits";
import {
  buildFirstFramePrompt,
  buildLastFramePrompt,
} from "@/lib/ai/prompts/frame-generate";
import { buildSceneFramePrompt } from "@/lib/ai/prompts/scene-frame-generate";
import { resolveImageProvider, resolveVideoProvider, resolveAIProvider } from "@/lib/ai/provider-factory";
import { buildVideoPrompt, buildReferenceVideoPrompt } from "@/lib/ai/prompts/video-generate";
import { buildRefVideoPromptRequest } from "@/lib/ai/prompts/ref-video-prompt-generate";
import { buildCharacterTurnaroundPrompt } from "@/lib/ai/prompts/character-image";
import { assembleVideo } from "@/lib/video/ffmpeg";
import { parseRefImages, serializeRefImages, appendToHistory, type RefImage } from "@/lib/ref-image-utils";
import {
  loadShotLegacyView,
  loadShotLegacyViewsBatch,
  getActiveAsset,
  getLatestCompletedAsset,
  insertAssetVersion,
  patchAsset,
  copyToUploads,
  stripCharHint,
} from "@/lib/shot-asset-utils";
import { buildRefImagePromptsRequest } from "@/lib/ai/prompts/ref-image-prompts";
import { buildKeyframePromptsRequest } from "@/lib/ai/prompts/keyframe-prompts";
import { ratioToSize } from "@/lib/ai/size";
import { getUploadDir } from "@/lib/env";

export const maxDuration = 300;



/** Fetch characters linked to an episode via episode_characters, or all project characters if no episode. */
async function getEpisodeCharacters(projectId: string, epId?: string | null) {
  if (epId) {
    // Priority 1: linked via episode_characters join table (instance rows, Type B)
    const linkedIds = await db
      .select({ characterId: episodeCharacters.characterId })
      .from(episodeCharacters)
      .where(eq(episodeCharacters.episodeId, epId));
    if (linkedIds.length > 0) {
      return db.select().from(characters).where(inArray(characters.id, linkedIds.map((r) => r.characterId)));
    }
    // Priority 2: direct lookup by episode_id on characters table (instance rows without join)
    const directInstances = await db.select().from(characters).where(eq(characters.episodeId, epId));
    if (directInstances.length > 0) {
      return directInstances;
    }
    // Priority 3: fallback to project-level template rows (Type A, episode_id=null)
    return db.select().from(characters).where(and(
      eq(characters.projectId, projectId),
      isNull(characters.episodeId)
    ));
  }
  return db.select().from(characters).where(eq(characters.projectId, projectId));
}

/**
 * Check if a character is visible on-screen by looking for their name
 * in the videoScript or startFrameDesc fields.
 */
function isCharacterOnScreen(
  characterName: string,
  videoScript: string,
  startFrameDesc: string | null | undefined
): boolean {
  const text = `${videoScript} ${startFrameDesc ?? ""}`;
  return text.includes(characterName);
}


/**
 * Build character mapping prompt prefix for image generation.
 * Includes character name, height, body type, description, and strict
 * proportion enforcement when multiple characters are present.
 */
function buildCharMappingPrefix(chars: Array<typeof characters.$inferSelect>): string {
  if (chars.length === 0) return "";
  const charMapping = chars.map((c, i) => `图片${i + 1}=${c.name}`).join("，");
  const charDescriptions = chars
    .map((c) => {
      const heightInfo = c.heightCm ? `身高约${c.heightCm}cm` : "";
      const bodyInfo = c.bodyType ? `${c.bodyType}体型` : "";
      const physicalTags = [heightInfo, bodyInfo].filter(Boolean).join("，");
      return `${c.name}${physicalTags ? `（${physicalTags}）` : ""}: ${c.description || ""}`;
    })
    .join("\n");
  const heightHint = chars.length > 1
    ? `\n\n【角色比例严格要求】画面中角色的相对身高/体型必须严格遵循上述身高数据。儿童必须明显小于成人，体型矮小、头身比例符合实际年龄，绝不可画成与成人同等大小。`
    : "";
  return `角色映射：${charMapping}\n\n角色描述：\n${charDescriptions}${heightHint}\n\n严格按照参考图的角色外观（面部、服装、发型）和相对比例生成。\n\n场景描述：`;
}

async function getVersionedUploadDir(versionId: string | null | undefined): Promise<string> {
  if (!versionId) return getUploadDir();
  const [version] = await db
    .select({ label: storyboardVersions.label, projectId: storyboardVersions.projectId })
    .from(storyboardVersions)
    .where(eq(storyboardVersions.id, versionId));
  if (!version) return getUploadDir();
  return path.join(getUploadDir(), "projects", version.projectId, version.label);
}

function extractErrorMessage(err: unknown): string {
  if (!(err instanceof Error)) return String(err);
  // Try to parse JSON error bodies (e.g. Google GenAI ApiError)
  try {
    const parsed = JSON.parse(err.message) as { error?: { message?: string } };
    if (parsed?.error?.message) return parsed.error.message;
  } catch {}
  return err.message;
}

interface ModelConfig {
  text?: ProviderConfig | null;
  image?: ProviderConfig | null;
  video?: ProviderConfig | null;
}

async function findBoundAgent(projectId: string, category: AgentCategory) {
  const [binding] = await db
    .select({ agentId: agentBindings.agentId })
    .from(agentBindings)
    .where(
      and(
        eq(agentBindings.projectId, projectId),
        eq(agentBindings.category, category),
      ),
    );
  if (!binding?.agentId) {
    console.log(`[findBoundAgent] ${category}: no binding for project ${projectId}`);
    return null;
  }
  const [agent] = await db.select().from(agents).where(eq(agents.id, binding.agentId));
  console.log(`[findBoundAgent] ${category}: found agent "${agent?.name}" (platform=${agent?.platform}, appId=${agent?.appId?.slice(0, 10)}...)`);
  return agent ?? null;
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params;
  const userId = getUserIdFromRequest(request);

  // Verify project ownership
  const [ownerCheck] = await db
    .select({ id: projects.id })
    .from(projects)
    .where(and(eq(projects.id, projectId), eq(projects.userId, userId)));
  if (!ownerCheck) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const body = (await request.json()) as {
    action: string;
    payload?: Record<string, unknown>;
    modelConfig?: ModelConfig;
    episodeId?: string;
  };

  const { action, payload, modelConfig, episodeId } = body;
  console.log(`[Generate] action=${action}, projectId=${projectId}, episodeId=${episodeId || "none"}`);

  if (action === "script_outline") {
    return handleScriptOutlineAction(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "script_generate") {
    return handleScriptGenerate(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "script_parse") {
    return handleScriptParseStream(projectId, userId, modelConfig, episodeId);
  }

  if (action === "character_extract") {
    return handleCharacterExtract(projectId, userId, modelConfig, episodeId);
  }

  if (action === "single_character_image") {
    return handleSingleCharacterImage(payload, modelConfig);
  }

  if (action === "batch_character_image") {
    return handleBatchCharacterImage(projectId, modelConfig, episodeId);
  }

  if (action === "shot_split") {
    return handleShotSplitStream(projectId, userId, modelConfig, episodeId);
  }

  if (action === "generate_keyframe_prompts") {
    return handleGenerateKeyframePrompts(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_shot_rewrite") {
    return handleSingleShotRewrite(projectId, payload, modelConfig, episodeId);
  }

  if (action === "batch_frame_generate") {
    return handleBatchFrameGenerate(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_frame_generate") {
    return handleSingleFrameGenerate(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_video_generate") {
    return handleSingleVideoGenerate(projectId, userId, payload, modelConfig);
  }

  if (action === "batch_video_generate") {
    return handleBatchVideoGenerate(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_scene_frame") {
    return handleSingleSceneFrame(projectId, userId, payload, modelConfig);
  }

  if (action === "batch_scene_frame") {
    return handleBatchSceneFrame(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_reference_video") {
    return handleSingleReferenceVideo(projectId, userId, payload, modelConfig);
  }

  if (action === "batch_reference_video") {
    return handleBatchReferenceVideo(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_video_prompt") {
    return handleSingleVideoPrompt(projectId, userId, payload, modelConfig);
  }

  if (action === "batch_video_prompt") {
    return handleBatchVideoPrompt(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "ai_optimize_text") {
    return handleAiOptimizeText(payload, modelConfig);
  }

  if (action === "video_assemble") {
    return handleVideoAssembleSync(projectId, payload, episodeId);
  }

  if (action === "batch_ref_image_generate") {
    return handleBatchRefImageGenerate(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_ref_image_generate") {
    return handleSingleRefImageGenerate(projectId, userId, payload, modelConfig);
  }

  if (action === "generate_ref_prompts") {
    return handleGenerateRefPrompts(projectId, userId, payload, modelConfig, episodeId);
  }

  if (action === "single_ref_image_generate_all") {
    return handleSingleShotRefImageGenerateAll(projectId, userId, payload, modelConfig);
  }

  // Image/video generation - keep in task queue
  const task = await enqueueTask({
    type: action as NonNullable<TaskType>,
    projectId,
    payload: { projectId, ...payload, modelConfig, episodeId, userId },
    ...(episodeId ? { episodeId } : {}),
  });

  return NextResponse.json(task, { status: 201 });
}

// --- script_outline: stream plain text outline from an idea ---

async function handleScriptOutlineAction(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  const idea = (payload?.idea as string) || "";
  if (!idea.trim()) {
    return NextResponse.json({ error: "No idea provided" }, { status: 400 });
  }

  // === 智能体路由（流式）===
  const boundAgent = await findBoundAgent(projectId, "script_outline");
  if (boundAgent) {
    try {
      const agentStream = await callAgentStream(
        { platform: boundAgent.platform as "bailian" | "dify" | "coze", appId: boundAgent.appId, apiKey: boundAgent.apiKey },
        `创意构想：${idea}`,
      );
      // TransformStream: accumulate chunks, save to DB in flush (tied to response lifecycle)
      const decoder = new TextDecoder();
      let outlineBuf = "";
      const saveTransform = new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          outlineBuf += decoder.decode(chunk, { stream: true });
          controller.enqueue(chunk);
        },
        async flush() {
          const outline = outlineBuf.trim();
          if (!outline) return;
          try {
            if (episodeId) {
              await db.update(episodes).set({ outline, updatedAt: new Date() }).where(eq(episodes.id, episodeId));
            } else {
              await db.update(projects).set({ outline, updatedAt: new Date() }).where(eq(projects.id, projectId));
            }
            console.log(`[ScriptOutline Agent] Saved outline (${outline.length} chars)`);
          } catch (err) {
            console.error(`[ScriptOutline Agent] DB save failed:`, err);
          }
        },
      });
      return new Response(agentStream.pipeThrough(saveTransform), {
        headers: { "Content-Type": "text/plain; charset=utf-8", "Transfer-Encoding": "chunked" },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error(`[Agent script_outline] Error:`, message);
      return NextResponse.json({ error: message }, { status: 422 });
    }
  }
  // === 智能体路由结束 ===

  if (!modelConfig?.text) {
    return NextResponse.json(
      { error: "No text model configured" },
      { status: 400 }
    );
  }

  const model = createLanguageModel(modelConfig.text);
  const outlineSystem = await resolvePrompt("script_outline", { userId, projectId });

  const result = streamText({
    model,
    system: outlineSystem,
    prompt: `创意构想：${idea}`,
    temperature: 0.7,
    onFinish: async ({ text }) => {
      try {
        const outline = text.trim();
        if (episodeId) {
          await db
            .update(episodes)
            .set({ outline, updatedAt: new Date() })
            .where(eq(episodes.id, episodeId));
        } else {
          await db
            .update(projects)
            .set({ outline, updatedAt: new Date() })
            .where(eq(projects.id, projectId));
        }
        console.log(`[ScriptOutline] Saved outline for ${episodeId || projectId}`);
      } catch (err) {
        console.error("[ScriptOutline] onFinish error:", err);
      }
    },
  });

  return result.toTextStreamResponse();
}

// --- script_generate: stream plain text screenplay from an idea ---

async function handleScriptGenerate(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  const idea = (payload?.idea as string) || "";
  if (!idea.trim()) {
    return NextResponse.json({ error: "No idea provided" }, { status: 400 });
  }

  // Save the original idea before generating
  if (episodeId) {
    await db
      .update(episodes)
      .set({ idea, updatedAt: new Date() })
      .where(eq(episodes.id, episodeId));
  } else {
    await db
      .update(projects)
      .set({ idea, updatedAt: new Date() })
      .where(eq(projects.id, projectId));
  }

  // === 智能体路由（流式）===
  const sgBoundAgent = await findBoundAgent(projectId, "script_generate");
  if (sgBoundAgent) {
    try {
      const outline = (payload?.outline as string) || "";
      const agentPrompt = outline
        ? `创意构想：${idea}\n\n故事大纲：${outline}`
        : `创意构想：${idea}`;
      const agentStream = await callAgentStream(
        { platform: sgBoundAgent.platform as "bailian" | "dify" | "coze", appId: sgBoundAgent.appId, apiKey: sgBoundAgent.apiKey },
        agentPrompt,
      );
      const sgDecoder = new TextDecoder();
      let scriptBuf = "";
      const sgSaveTransform = new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          scriptBuf += sgDecoder.decode(chunk, { stream: true });
          controller.enqueue(chunk);
        },
        async flush() {
          const script = scriptBuf.trim();
          if (!script) return;
          try {
            if (episodeId) {
              await db.update(episodes).set({ script, updatedAt: new Date() }).where(eq(episodes.id, episodeId));
            } else {
              await db.update(projects).set({ script, updatedAt: new Date() }).where(eq(projects.id, projectId));
            }
            console.log(`[ScriptGenerate Agent] Saved script (${script.length} chars)`);
          } catch (err) {
            console.error(`[ScriptGenerate Agent] DB save failed:`, err);
          }
        },
      });
      return new Response(agentStream.pipeThrough(sgSaveTransform), {
        headers: { "Content-Type": "text/plain; charset=utf-8", "Transfer-Encoding": "chunked" },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error(`[Agent script_generate] Error:`, message);
      return NextResponse.json({ error: message }, { status: 422 });
    }
  }
  // === 智能体路由结束 ===

  if (!modelConfig?.text) {
    return NextResponse.json(
      { error: "No text model configured" },
      { status: 400 }
    );
  }

  // Use outline from payload (latest from UI) or fallback to DB
  let outline = (payload?.outline as string) || "";
  if (!outline) {
    if (episodeId) {
      const [ep] = await db.select({ outline: episodes.outline }).from(episodes).where(eq(episodes.id, episodeId));
      outline = ep?.outline || "";
    } else {
      const [proj] = await db.select({ outline: projects.outline }).from(projects).where(eq(projects.id, projectId));
      outline = proj?.outline || "";
    }
  }

  const outlineContext = outline
    ? `\n\n【故事大纲 - 请严格按照以下大纲结构展开剧本】\n${outline}\n\n`
    : "";

  // Fetch world setting from project
  let worldSettingContext = "";
  const [projForWorld] = await db.select({ worldSetting: projects.worldSetting }).from(projects).where(eq(projects.id, projectId));
  if (projForWorld?.worldSetting) {
    worldSettingContext = `\n\n【世界观设定】\n${projForWorld.worldSetting}\n\n剧本必须与此世界观设定保持一致。\n\n`;
  }

  const model = createLanguageModel(modelConfig.text);
  const scriptGenerateSystem = await resolvePrompt("script_generate", { userId, projectId });

  const result = streamText({
    model,
    system: scriptGenerateSystem,
    prompt: worldSettingContext + outlineContext + buildScriptGeneratePrompt(idea),
    temperature: 0.8,
    onFinish: async ({ text }) => {
      try {
        if (episodeId) {
          await db
            .update(episodes)
            .set({ script: text, updatedAt: new Date() })
            .where(eq(episodes.id, episodeId));
        } else {
          await db
            .update(projects)
            .set({ script: text, updatedAt: new Date() })
            .where(eq(projects.id, projectId));
        }
        console.log(`[ScriptGenerate] Saved generated script for ${episodeId || projectId}`);
      } catch (err) {
        console.error("[ScriptGenerate] onFinish error:", err);
      }
    },
  });

  return result.toTextStreamResponse();
}

// --- script_parse: parse user script into structured screenplay ---

async function handleScriptParseStream(
  projectId: string,
  userId: string,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  let script: string | null = null;

  if (episodeId) {
    const [episode] = await db.select().from(episodes).where(eq(episodes.id, episodeId));
    script = episode?.script ?? null;
  } else {
    const [project] = await db.select().from(projects).where(eq(projects.id, projectId));
    script = project?.script ?? null;
  }

  if (!script) {
    return NextResponse.json(
      { error: "Project or script not found" },
      { status: 404 }
    );
  }

    // === 智能体路由（流式）===
  const boundAgent = await findBoundAgent(projectId, "script_parse");
  if (boundAgent) {
    try {
      const agentStream = await callAgentStream(
        { platform: boundAgent.platform as "bailian" | "dify" | "coze", appId: boundAgent.appId, apiKey: boundAgent.apiKey },
        script,
      );
      const spSaveTransform = new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) { controller.enqueue(chunk); },
        async flush() {
          try {
            if (episodeId) {
              await db.update(episodes).set({ updatedAt: new Date() }).where(eq(episodes.id, episodeId));
            } else {
              await db.update(projects).set({ updatedAt: new Date() }).where(eq(projects.id, projectId));
            }
            console.log(`[ScriptParse Agent] Updated timestamp`);
          } catch (err) {
            console.error(`[ScriptParse Agent] DB update failed:`, err);
          }
        },
      });
      return new Response(agentStream.pipeThrough(spSaveTransform), {
        headers: { "Content-Type": "text/plain; charset=utf-8", "Transfer-Encoding": "chunked" },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error(`[Agent script_parse] Error:`, message);
      return NextResponse.json({ error: message }, { status: 422 });
    }
  }
  // === 智能体路由结束 ===

  if (!modelConfig?.text) {
    return NextResponse.json(
      { error: "No text model configured" },
      { status: 400 }
    );
  }

  const model = createLanguageModel(modelConfig.text);
  const scriptParseSystem = await resolvePrompt("script_parse", { userId, projectId });

  const result = streamText({
    model,
    system: scriptParseSystem,
    prompt: buildScriptParsePrompt(script),
    temperature: 0.7,
    onFinish: async ({ text }) => {
      try {
        const screenplay = extractJSON(text);
        JSON.parse(screenplay); // validate JSON
        if (episodeId) {
          await db.update(episodes).set({ updatedAt: new Date() }).where(eq(episodes.id, episodeId));
        } else {
          await db.update(projects).set({ updatedAt: new Date() }).where(eq(projects.id, projectId));
        }
        console.log(`[ScriptParse] Parsed screenplay for ${episodeId || projectId}`);
      } catch (err) {
        console.error("[ScriptParse] onFinish error:", err);
      }
    },
  });

  return result.toTextStreamResponse();
}

// --- character_extract: stream character extraction from script ---

async function handleCharacterExtract(
  projectId: string,
  userId: string,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  let script: string | null = null;

  if (episodeId) {
    const [episode] = await db.select().from(episodes).where(eq(episodes.id, episodeId));
    script = episode?.script ?? null;
  } else {
    // Full project extraction: build prompt from EP split fields + character registry
    // (avoids context explosion from concatenating full screenplays)
    const allEps = await db.select({
      id: episodes.id,
      title: episodes.title,
      description: episodes.description,
      idea: episodes.idea,
      sequence: episodes.sequence,
    })
      .from(episodes)
      .where(eq(episodes.projectId, projectId))
      .orderBy(episodes.sequence);

    // For each EP, fetch linked character names
    const epCharNames = new Map<string, string[]>();
    for (const ep of allEps) {
      const links = await db
        .select({ name: characters.name })
        .from(episodeCharacters)
        .leftJoin(characters, eq(episodeCharacters.characterId, characters.id))
        .where(eq(episodeCharacters.episodeId, ep.id));
      epCharNames.set(ep.id, links.map((l) => l.name).filter((n): n is string => n !== null));
    }

    // Build per-EP input (base registry appended later after existingChars loaded)
    script = allEps.map((ep, i) => {
      const chars = epCharNames.get(ep.id) || [];
      return [
        `### EP${String(i + 1).padStart(2, "0")} ${ep.title}`,
        `构思: ${ep.idea || "（无）"}`,
        `描述: ${ep.description || "（无）"}`,
        `出场角色: ${chars.length > 0 ? chars.join("、") : "（待补充）"}`,
      ].join("\n");
    }).join("\n\n");

    if (!script.trim()) {
      // Fallback to project-level script if no EP data
      const [project] = await db.select().from(projects).where(eq(projects.id, projectId));
      script = project?.script ?? null;
    }
  }

  if (!script) {
    return NextResponse.json(
      { error: "Project or script not found" },
      { status: 404 }
    );
  }

  // Fetch all existing project characters for dedup
  const existingChars = await db
    .select()
    .from(characters)
    .where(eq(characters.projectId, projectId));

  // Build base character registry from template rows (for LLM prompt)
  if (!episodeId && script) {
    const templateChars = existingChars.filter((c) => !c.episodeId);
    if (templateChars.length > 0) {
      const baseRegistry = "\n\n=== 基础角色注册表（请复用 baseName，不要创建同名新角色）===\n" +
        templateChars.map((c) =>
          `- ${c.baseName || c.name}: ${c.scope === "main" ? "主角" : "配角"}。${c.description?.slice(0, 100) || ""}`
        ).join("\n");
      script = script + baseRegistry;
    }
  }

  // Build existing character registry for incremental extraction (S5)
  const existingByName = new Map(
    existingChars.filter((c) => !c.episodeId).map((c) => [c.name.toLowerCase().trim(), c])
  );
  const existingRegistry = existingChars
    .filter((c) => c.episodeId && c.baseName)
    .reduce((acc, c) => {
      const existing = acc.find((r) => r.baseName === c.baseName);
      if (existing) {
        existing.episodes.push({ epIndex: existing.episodes.length + 1, visualHint: c.visualHint || "" });
      } else if (c.baseName) {
        acc.push({ baseName: c.baseName, episodes: [{ epIndex: 1, visualHint: c.visualHint || "" }] });
      }
      return acc;
    }, [] as Array<{ baseName: string; episodes: Array<{ epIndex: number; visualHint: string }> }>);

  // Clear old episode_characters links before re-creating
  let oldEpisodeCharIds: string[] = [];
  if (episodeId) {
    const oldLinks = await db
      .select({ characterId: episodeCharacters.characterId })
      .from(episodeCharacters)
      .where(eq(episodeCharacters.episodeId, episodeId));
    oldEpisodeCharIds = oldLinks.map((l) => l.characterId);
    await db.delete(episodeCharacters).where(eq(episodeCharacters.episodeId, episodeId));
  } else {
    // Project-level: capture all episode-linked char IDs for relation scoping,
    // then delete all episode_characters for this project
    const allLinks = await db
      .select({ id: episodeCharacters.id, characterId: episodeCharacters.characterId })
      .from(episodeCharacters)
      .leftJoin(characters, eq(episodeCharacters.characterId, characters.id))
      .where(eq(characters.projectId, projectId));
    oldEpisodeCharIds = allLinks.map((l) => l.characterId);
    if (allLinks.length > 0) {
      const linkIds = allLinks.map((l) => l.id);
      for (const lid of linkIds) {
        await db.delete(episodeCharacters).where(eq(episodeCharacters.id, lid));
      }
    }
  }

  let aiText: string;
  const boundAgent = await findBoundAgent(projectId, "character_extract");
  if (boundAgent) {
    const agentResult = await callAndValidateAgent(boundAgent, "character_extract", buildCharacterExtractPrompt(script, existingRegistry.length > 0 ? existingRegistry : undefined));
    if (agentResult instanceof NextResponse) return agentResult;
    aiText = agentResult.text;
  } else {
    if (!modelConfig?.text) {
      return NextResponse.json({ error: "No text model configured" }, { status: 400 });
    }
    const model = createLanguageModel(modelConfig.text);
    const charExtractSystem = await resolvePrompt("character_extract", { userId, projectId });
    console.log("[CharacterExtract] resolved system prompt:\n", charExtractSystem);
    const { text } = await generateText({
      model,
      system: charExtractSystem,
      prompt: buildCharacterExtractPrompt(script, existingRegistry.length > 0 ? existingRegistry : undefined),
    });
    aiText = text;
  }

  const parsed = parseLLMJSON(aiText);

  // Debug: log raw format to verify per-EP output
  const rawChars: any[] = Array.isArray(parsed) ? parsed : (parsed.characters || []);
  if (rawChars.length > 0) {
    const first = rawChars[0];
    console.log(`[CharacterExtract] LLM returned ${rawChars.length} chars, format: ${first.episodes ? 'per-EP' : 'flat'}, first char: ${JSON.stringify(first).slice(0, 300)}`);
  }

  // Support new per-EP format: characters with episodes array
  // Also support legacy { characters, relationships } and flat array
  const extractedRelations: Array<{
    characterA: string;
    characterB: string;
    relationType: string;
    description?: string;
  }> = Array.isArray(parsed) ? [] : (parsed.relationships || []);

  let reusedCount = 0;
  let createdCount = 0;
  const linkedCharIds = new Set<string>();

  // Resolve EP IDs: script may use episodeIndex → need to map to actual episode IDs
  const allEps = episodeId
    ? [await db.select().from(episodes).where(eq(episodes.id, episodeId)).then((r) => r[0])]
    : await db.select().from(episodes).where(eq(episodes.projectId, projectId)).orderBy(episodes.sequence);
  const epByIndex = new Map<number, typeof allEps[0]>();
  allEps.forEach((ep, i) => { if (ep) epByIndex.set(i + 1, ep); });
  // Fallback: if no episodes table entries, use the single episodeId parameter
  if (epByIndex.size === 0 && episodeId) {
    const ep = await db.select().from(episodes).where(eq(episodes.id, episodeId)).then((r) => r[0]);
    if (ep) epByIndex.set(1, ep);
  }

  for (const raw of rawChars) {
    const baseName = raw.baseName || raw.name || "";
    const episodes: Array<{ episodeIndex: number; visualHint?: string; description?: string }> =
      raw.episodes || [{ episodeIndex: 1, visualHint: raw.visualHint, description: raw.description }];

    // S2: Create/update template row (Type A: episode_id=null)
    const templateKey = baseName.toLowerCase().trim();
    let templateId = existingByName.get(templateKey)?.id;
    if (!templateId) {
      templateId = genId();
      await db.insert(characters).values({
        id: templateId,
        projectId,
        baseName,
        name: baseName,
        description: episodes[0]?.description || raw.description || "",
        visualHint: episodes[0]?.visualHint || raw.visualHint || "",
        heightCm: raw.heightCm || 0,
        bodyType: raw.bodyType || "average",
        performanceStyle: raw.performanceStyle || "",
        scope: (raw.scope === "guest" ? "guest" : "main") as "main" | "guest",
        episodeId: null,
      });
      existingByName.set(templateKey, { id: templateId, name: baseName } as any);
      console.log(`[CharacterExtract] Created template row "${baseName}" (${templateId})`);
      createdCount++;
    } else {
      // Update template description from first EP's data
      await db.update(characters)
        .set({
          description: episodes[0]?.description || raw.description || "",
          scope: (raw.scope === "guest" ? "guest" : "main") as "main" | "guest",
        })
        .where(eq(characters.id, templateId));
      console.log(`[CharacterExtract] Reused template "${baseName}" (${templateId})`);
      reusedCount++;
    }

    // S2: Create/update episode instance rows (Type B: episode_id set)
    for (const epVar of episodes) {
      const ep = epByIndex.get(epVar.episodeIndex);
      if (!ep) {
        console.warn(`[CharacterExtract] No episode found for index ${epVar.episodeIndex}, skipping "${baseName}"`);
        continue;
      }

      // Check if instance row already exists for this baseName + episode
      const [existingInstance] = await db.select()
        .from(characters)
        .where(and(
          eq(characters.baseName, baseName),
          eq(characters.episodeId, ep.id)
        ));

      if (existingInstance) {
        await db.update(characters)
          .set({
            visualHint: epVar.visualHint || "",
            description: epVar.description || "",
          })
          .where(eq(characters.id, existingInstance.id));
        linkedCharIds.add(existingInstance.id);
      } else {
        const instId = genId();
        await db.insert(characters).values({
          id: instId,
          projectId,
          baseName,
          name: `${baseName}（${epVar.visualHint || ""}）`,
          description: epVar.description || "",
          visualHint: epVar.visualHint || "",
          heightCm: raw.heightCm || 0,
          bodyType: raw.bodyType || "average",
          performanceStyle: raw.performanceStyle || "",
          scope: (raw.scope === "guest" ? "guest" : "main") as "main" | "guest",
          episodeId: ep.id,
        });
        linkedCharIds.add(instId);
      }
    }
  }

  // Create episode_characters links for ALL instance rows created/updated
  // (not just the requested episodeId — per-EP variants span multiple episodes)
  // We already collected linkedCharIds (instance row IDs) in the loop above.
  if (linkedCharIds.size > 0) {
    // Wipe existing episode_characters links for this character set
    // then re-insert. We scope by all episode IDs that had variants processed.
    const processedEpIds = allEps.filter((ep) => ep).map((ep) => ep!.id);
    if (processedEpIds.length > 0) {
      // Remove old links for episodes we processed
      for (const charId of linkedCharIds) {
        const [charRow] = await db.select().from(characters).where(eq(characters.id, charId));
        if (charRow?.episodeId && processedEpIds.includes(charRow.episodeId)) {
          const [existingLink] = await db.select()
            .from(episodeCharacters)
            .where(and(
              eq(episodeCharacters.episodeId, charRow.episodeId),
              eq(episodeCharacters.characterId, charId)
            ));
          if (!existingLink) {
            await db.insert(episodeCharacters).values({
              id: genId(),
              episodeId: charRow.episodeId,
              characterId: charId,
            });
          }
        }
      }
    }
  }

  // Auto-create character relationships from extraction — replace existing on re-run.
  // Scoping rule: a relation belongs to this episode iff BOTH endpoints are in the
  // episode's character list. Project-level extraction clears all project relations.
  if (extractedRelations.length > 0) {
    if (episodeId) {
      // Episode-scoped: only clear relations whose both endpoints were in this episode.
      if (oldEpisodeCharIds.length > 0) {
        await db
          .delete(characterRelations)
          .where(
            and(
              eq(characterRelations.projectId, projectId),
              inArray(characterRelations.characterAId, oldEpisodeCharIds),
              inArray(characterRelations.characterBId, oldEpisodeCharIds)
            )
          );
      }
    } else {
      // Project-level: clear everything for the project.
      await db.delete(characterRelations).where(eq(characterRelations.projectId, projectId));
    }

    const allChars = await db.select().from(characters).where(eq(characters.projectId, projectId));
    // Match relations by baseName (from new prompt format) or fall back to name
    const baseNameToIds = new Map<string, string[]>();
    for (const c of allChars) {
      const bn = (c.baseName || c.name).toLowerCase().trim();
      if (!baseNameToIds.has(bn)) baseNameToIds.set(bn, []);
      baseNameToIds.get(bn)!.push(c.id);
    }
    const nameToId = new Map(allChars.map((c) => [c.name, c.id]));

    for (const rel of extractedRelations) {
      // Try baseName match first (new format), then name match (legacy)
      const aBN = rel.characterA.toLowerCase().trim();
      const bBN = rel.characterB.toLowerCase().trim();
      const aIds = baseNameToIds.get(aBN) || (nameToId.has(rel.characterA) ? [nameToId.get(rel.characterA)!] : []);
      const bIds = baseNameToIds.get(bBN) || (nameToId.has(rel.characterB) ? [nameToId.get(rel.characterB)!] : []);
      // Use the first matching ID for each side (relations are between identities, not episode instances)
      const aId = aIds.length > 0 ? aIds[0] : undefined;
      const bId = bIds.length > 0 ? bIds[0] : undefined;
      if (aId && bId && aId !== bId) {
        try {
          await db.insert(characterRelations).values({
            id: genId(),
            projectId,
            characterAId: aId,
            characterBId: bId,
            relationType: rel.relationType || "neutral",
            description: rel.description || "",
          });
        } catch {
          // Skip duplicates
        }
      }
    }
  }

  console.log(
    `[CharacterExtract] ${rawChars.length} chars: ${reusedCount} reused, ${createdCount} new, ${linkedCharIds.size} linked to episodes, ${extractedRelations.length} relations`
  );

  return NextResponse.json({ characters: rawChars });
}

// --- single_character_image: generate turnaround image for one character ---

async function handleSingleCharacterImage(
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const characterId = payload?.characterId as string;
  if (!characterId) {
    return NextResponse.json({ error: "No characterId provided" }, { status: 400 });
  }

  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const [character] = await db
    .select()
    .from(characters)
    .where(eq(characters.id, characterId));

  if (!character) {
    return NextResponse.json({ error: "Character not found" }, { status: 404 });
  }

  const ai = resolveImageProvider(modelConfig);

  // Build front-view prompt from template system (matching pipeline/character-image.ts)
  const slotContents = await resolveSlotContents("character_image", { userId: "", projectId: character.projectId });
  const styleMatching = (slotContents as any)["style_matching"] || "";
  const faceDetail = (slotContents as any)["face_detail"] || "";
  const frontLayout = (slotContents as any)["front_view_layout"] || "";
  const charPrompt = [
    `角色正面参考图——四视图流程第一步。`,
    ``,
    `=== 角色描述 ===`,
    `${character.description || character.name}`,
    ``,
    faceDetail,
    ``,
    styleMatching,
    ``,
    frontLayout,
    ``,
    `光线：与角色描述中声明的一致（如 自然光粗粝质感、柔和布光），纯白背景。`,
  ].join("\n");

  const prompt = charPrompt;

  try {
    const rawImagePath = await ai.generateImage(prompt, {
      size: "2560x1440",
      aspectRatio: "16:9",
      quality: "hd",
      pipeline: "character-image",
      pipelineParams: {
        character_name: character.name,
        character_desc: character.description || character.name,
        character_prompt: charPrompt,
      },
    });

    // Copy to uploads for browser serving
    const imagePath = copyToUploads(rawImagePath, 'character_reference');

    // Append to history
    let history: string[] = [];
    try {
      history = JSON.parse(character.referenceImageHistory || "[]");
    } catch {}
    if (character.referenceImage && !history.includes(character.referenceImage)) {
      history.push(character.referenceImage);
    }
    if (!history.includes(imagePath)) {
      history.push(imagePath);
    }

    await db
      .update(characters)
      .set({ referenceImage: imagePath, referenceImageHistory: JSON.stringify(history) })
      .where(eq(characters.id, characterId));

    // Mark downstream ref images stale: any shot's referenceImages that include this character
    // as a "characters" entry should have its generated items reset to pending so they're
    // regenerated with the new character reference image.
    const allShots = await db.select().from(shots).where(eq(shots.projectId, character.projectId));
    const legacyMap = await loadShotLegacyViewsBatch(allShots.map((s) => s.id));
    let staleCount = 0;
    for (const shot of allShots) {
      const view = legacyMap.get(shot.id);
      if (!view) continue;
      const refItems = view.referenceImages;
      let modified = false;
      for (const item of refItems) {
        if (item.characters?.includes(character.name) && item.status === "completed") {
          await patchAsset(item.id, { status: "pending", fileUrl: null });
          modified = true;
        }
      }
      if (modified) {
        staleCount++;
      }
    }
    console.log(`[SingleCharacterImage] ${character.name} regenerated; marked ${staleCount} shots' ref images as stale`);

    return NextResponse.json({ characterId, imagePath, status: "ok", staleShots: staleCount });
  } catch (err) {
    console.error(`[SingleCharacterImage] Error for ${character.name}:`, err);
    return NextResponse.json({ characterId, status: "error", error: extractErrorMessage(err) }, { status: 500 });
  }
}

// --- batch_character_image: generate turnaround images for all characters ---

async function handleBatchCharacterImage(
  projectId: string,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  if (!modelConfig?.image) {
    return NextResponse.json(
      { error: "No image model configured" },
      { status: 400 }
    );
  }

  let allCharacters: typeof characters.$inferSelect[];
  if (episodeId) {
    const linkedIds = await db
      .select({ characterId: episodeCharacters.characterId })
      .from(episodeCharacters)
      .where(eq(episodeCharacters.episodeId, episodeId));
    allCharacters = linkedIds.length > 0
      ? await db.select().from(characters).where(inArray(characters.id, linkedIds.map((r) => r.characterId)))
      : [];
  } else {
    allCharacters = await db.select().from(characters).where(eq(characters.projectId, projectId));
  }

  const needImages = allCharacters.filter((c) => !c.referenceImage);
  if (needImages.length === 0) {
    return NextResponse.json({ results: [], message: "All characters already have images" });
  }

  const ai = resolveImageProvider(modelConfig);

  const results = await Promise.all(
    needImages.map(async (character) => {
      try {
        const prompt = buildCharacterTurnaroundPrompt(character.description || character.name, character.name);
        const rawImagePath = await ai.generateImage(prompt, {
          size: "2560x1440",
          aspectRatio: "16:9",
          quality: "hd",
          pipeline: "character-image",
          pipelineParams: {
            character_name: character.name,
            character_desc: character.description || character.name,
          },
        });

        // Copy to uploads for browser serving
        const imagePath = copyToUploads(rawImagePath, 'character_reference');

        // Append to history
        let history: string[] = [];
        try { history = JSON.parse(character.referenceImageHistory || "[]"); } catch {}
        if (character.referenceImage && !history.includes(character.referenceImage)) history.push(character.referenceImage);
        if (!history.includes(imagePath)) history.push(imagePath);

        await db
          .update(characters)
          .set({ referenceImage: imagePath, referenceImageHistory: JSON.stringify(history) })
          .where(eq(characters.id, character.id));
        return { characterId: character.id, name: character.name, imagePath, status: "ok" };
      } catch (err) {
        console.error(`[BatchCharacterImage] Error for ${character.name}:`, err);
        return { characterId: character.id, name: character.name, status: "error", error: extractErrorMessage(err) };
      }
    })
  );

  return NextResponse.json({ results });
}

// --- shot_split: stream shot splitting ---

async function handleShotSplitStream(
  projectId: string,
  userId: string,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  let script: string | null = null;
  let generationMode: string = "keyframe";
  if (episodeId) {
    const [episode] = await db.select().from(episodes).where(eq(episodes.id, episodeId));
    if (!episode) {
      return NextResponse.json({ error: "Episode not found" }, { status: 404 });
    }
    script = episode.script ?? null;
    generationMode = episode.generationMode ?? "keyframe";
  } else {
    const [project] = await db.select().from(projects).where(eq(projects.id, projectId));
    if (!project) {
      return NextResponse.json({ error: "Project not found" }, { status: 404 });
    }
    script = project.script ?? null;
    generationMode = project.generationMode ?? "keyframe";
  }

  // === 智能体路由 ===
  console.log(`[ShotSplit] projectId=${projectId}, episodeId=${episodeId}, script length=${script?.length ?? 0}`);
  {
    const boundAgent = await findBoundAgent(projectId, "shot_split");
    if (boundAgent) {
      if (!script) {
        // Agent 模式下也需要剧本 — 尝试从 episode 或 project 重新获取
        if (episodeId) {
          const [ep] = await db.select().from(episodes).where(eq(episodes.id, episodeId));
          script = ep?.script ?? null;
        }
        if (!script) {
          const [proj] = await db.select().from(projects).where(eq(projects.id, projectId));
          script = proj?.script ?? null;
        }
        if (!script) {
          return NextResponse.json({ error: "没有剧本内容，请先编写或生成剧本" }, { status: 400 });
        }
      }
      const agentResult = await callAndValidateAgent(boundAgent, "shot_split", script);
      if (agentResult instanceof NextResponse) return agentResult;

      // Parse agent output and save to DB (same logic as built-in pipeline)
      const agentParsed = parseLLMJSON(agentResult.text);
      let agentShots: ParsedShot[];
      if (Array.isArray(agentParsed) && agentParsed.length > 0 && agentParsed[0].shots) {
        agentShots = agentParsed.flatMap((scene: { sceneDescription?: string; shots?: ParsedShot[] }) =>
          (scene.shots || []).map((s) => ({ ...s, sceneDescription: s.sceneDescription || scene.sceneDescription || "" }))
        );
      } else if (Array.isArray(agentParsed)) {
        agentShots = agentParsed;
      } else {
        agentShots = agentParsed.shots || [];
      }
      agentShots.forEach((s, i) => { s.sequence = i + 1; });

      if (agentShots.length === 0) {
        return NextResponse.json({ error: "智能体未返回有效分镜数据" }, { status: 422 });
      }

      // Fetch characters for dialogue matching
      const agentCharacters = await getEpisodeCharacters(projectId, episodeId);

      // Create version
      const agentVerWhere = episodeId
        ? and(eq(storyboardVersions.projectId, projectId), eq(storyboardVersions.episodeId, episodeId))
        : eq(storyboardVersions.projectId, projectId);
      const [agentMaxVer] = await db.select({ maxNum: storyboardVersions.versionNum })
        .from(storyboardVersions).where(agentVerWhere).orderBy(desc(storyboardVersions.versionNum)).limit(1);
      const agentNextVer = (agentMaxVer?.maxNum ?? 0) + 1;
      const agentDate = new Date();
      const agentDateStr = agentDate.getUTCFullYear().toString() +
        String(agentDate.getUTCMonth() + 1).padStart(2, "0") +
        String(agentDate.getUTCDate()).padStart(2, "0");
      const agentVersionId = genId();
      await db.insert(storyboardVersions).values({
        id: agentVersionId, projectId, label: `${agentDateStr}-V${agentNextVer}`,
        versionNum: agentNextVer, createdAt: agentDate, episodeId: episodeId ?? null,
      });

      for (const shot of agentShots) {
        const shotId = genId();
        await db.insert(shots).values({
          id: shotId, projectId, versionId: agentVersionId,
          sequence: shot.sequence,
          prompt: shot.startFrame || shot.sceneDescription || "",
          motionScript: shot.motionScript || "",
          videoScript: shot.videoScript ?? null,
          cameraDirection: shot.cameraDirection || "static",
          duration: shot.duration || 8,
          transitionIn: shot.transitionIn || "cut",
          transitionOut: shot.transitionOut || "cut",
          compositionGuide: shot.compositionGuide || "",
          focalPoint: shot.focalPoint || "",
          depthOfField: shot.depthOfField || "medium",
          soundDesign: shot.soundDesign || "",
          musicCue: shot.musicCue || "",
          episodeId: episodeId ?? null,
        });
        for (let i = 0; i < (shot.dialogues || []).length; i++) {
          const d = shot.dialogues[i];
          const mc = agentCharacters.find((c) => c.name === d.character);
          if (mc) {
            await db.insert(dialogues).values({ id: genId(), shotId, characterId: mc.id, text: d.text, sequence: i });
          }
        }
      }
      console.log(`[ShotSplit Agent] Created ${agentShots.length} shots`);
      return NextResponse.json({ shots: agentShots.length });
    }
  }
  // === 智能体路由结束 ===

  if (!modelConfig?.text) {
    return NextResponse.json(
      { error: "No text model configured" },
      { status: 400 }
    );
  }

  // Fetch only characters linked to this episode
  let shotCharacters: typeof characters.$inferSelect[];
  if (episodeId) {
    const linkedIds = await db
      .select({ characterId: episodeCharacters.characterId })
      .from(episodeCharacters)
      .where(eq(episodeCharacters.episodeId, episodeId));
    shotCharacters = linkedIds.length > 0
      ? await db.select().from(characters).where(inArray(characters.id, linkedIds.map((r) => r.characterId)))
      : [];
  } else {
    shotCharacters = await db.select().from(characters).where(eq(characters.projectId, projectId));
  }

  const characterDescriptions = shotCharacters
    .map((c) => `${c.name}${c.visualHint ? `（${c.visualHint}）` : ""}: ${c.description}`)
    .join("\n");

  const characterVisualHints = shotCharacters
    .filter((c) => c.visualHint)
    .map((c) => ({ name: c.name, visualHint: c.visualHint! }));

  const characterPerformanceStyles = shotCharacters
    .filter((c) => c.performanceStyle)
    .map((c) => ({ name: c.name, performanceStyle: c.performanceStyle! }));

  // Load character relationships — CRITICAL for shot planning. Without
  // this block the LLM treats enemies as bystanders (e.g. "如来佛祖" gets
  // rendered as a Buddha statue in the background instead of an active
  // combatant against 孙悟空).
  const shotRelations = await db
    .select()
    .from(characterRelations)
    .where(eq(characterRelations.projectId, projectId));
  let relationsText = "";
  if (shotRelations.length > 0) {
    relationsText = "\n\n## 角色关系（必须用于决定站位、眼神、肢体对抗、画面张力）\n";
    for (const rel of shotRelations) {
      const charA = shotCharacters.find((c) => c.id === rel.characterAId);
      const charB = shotCharacters.find((c) => c.id === rel.characterBId);
      if (charA && charB) {
        relationsText += `- ${charA.name} ↔ ${charB.name}：${rel.relationType}${rel.description ? `（${rel.description}）` : ""}\n`;
      }
    }
    relationsText += `
**关系驱动构图规则（最高优先级）**：
- **敌对 / 对立 / 仇人**：两人必须都是**活人角色同屏对峙**——直接对视、肢体对抗、武器对准彼此。禁止把任一方画成背景的雕像/神像/虚影/浮雕。
- **友好 / 盟友**：并肩、相互掩护、眼神交流。
- **爱慕 / 亲密**：靠近、牵手、拥抱、温柔对视。
- **父女 / 师徒**：长辈在前/侧，晚辈在后/侧随从。
- 任何被标记为角色关系的双方，在包含他们的镜头中都必须作为**真实的活人**出现，而不是背景装饰。
`;
  }

  // Fetch world setting and target duration from project
  const [projData] = await db.select({ worldSetting: projects.worldSetting, targetDuration: projects.targetDuration }).from(projects).where(eq(projects.id, projectId));
  let targetDuration = projData?.targetDuration || 0;
  if (episodeId) {
    const [epDur] = await db.select({ targetDuration: episodes.targetDuration }).from(episodes).where(eq(episodes.id, episodeId));
    if (epDur?.targetDuration && epDur.targetDuration > 0) targetDuration = epDur.targetDuration;
  }

  const model = createLanguageModel(modelConfig.text);
  const videoMaxDuration = getModelMaxDuration(modelConfig?.video?.modelId);
  const shotSplitSlots = await resolveSlotContents("shot_split", { userId, projectId });
  const shotSplitDef = getPromptDefinition("shot_split")!;
  const systemPrompt = shotSplitDef.buildFullPrompt(shotSplitSlots, { maxDuration: videoMaxDuration });
  const jsonMode = { openai: { response_format: { type: "json_object" } } };

  // Split screenplay into chunks by SCENE markers (~8 scenes per chunk)
  const fullScript = script || "";
  const sceneChunks = splitScriptByScenes(fullScript, 8);
  // Log scene detection details
  const sceneRe = /^[\s*#]*(?:SCENE|场景)\s*\d+/i;
  const sceneMatches = fullScript.split("\n").filter((l) => sceneRe.test(l.trim()));
  console.log(`[ShotSplit] Detected ${sceneMatches.length} scenes, split into ${sceneChunks.length} chunk(s) of ~8 scenes each`);
  sceneChunks.forEach((c, i) => {
    const sceneCount = c.split("\n").filter((l) => sceneRe.test(l.trim())).length;
    console.log(`[ShotSplit] Chunk ${i + 1}: ${sceneCount} scenes, ${c.length} chars`);
  });

  type ParsedShot = {
    sequence: number;
    sceneDescription: string;
    startFrame: string;
    endFrame: string;
    motionScript: string;
    videoScript?: string;
    duration: number;
    dialogues: Array<{ character: string; text: string }>;
    cameraDirection?: string;
    transitionIn?: string;
    transitionOut?: string;
    compositionGuide?: string;
    focalPoint?: string;
    depthOfField?: string;
    soundDesign?: string;
    musicCue?: string;
    characters?: string[];
    referenceImagePrompts?: string[];
  };

  // Process chunks concurrently
  const chunkResults = await Promise.all(
    sceneChunks.map(async (chunk, idx) => {
      let prompt = buildShotSplitPrompt(chunk, characterDescriptions, characterVisualHints, undefined, characterPerformanceStyles.length > 0 ? characterPerformanceStyles : undefined);

      // Inject character relations (drives on-screen interaction framing)
      if (relationsText) prompt += relationsText;

      // Inject world setting
      if (projData?.worldSetting) {
        prompt = `【世界观设定】\n${projData.worldSetting}\n\n所有镜头必须与此世界观设定保持一致。\n\n` + prompt;
      }

      // Inject target duration
      if (targetDuration && targetDuration > 0) {
        prompt += `\n\n目标总时长：${targetDuration}秒（${Math.floor(targetDuration / 60)}分${targetDuration % 60}秒）。请确保所有镜头的时长之和接近此目标。\n`;
      }
      try {
        const result = await generateText({
          model,
          system: systemPrompt,
          prompt,
          providerOptions: jsonMode,
        });
        const parsed = parseLLMJSON(result.text);
        // Handle multiple formats:
        // 1. Scene-grouped: [{ sceneTitle, shots: [...] }]
        // 2. Flat with wrapper: { shots: [...] }
        // 3. Flat array: [{ sequence, ... }]
        let shotList: ParsedShot[];
        if (Array.isArray(parsed) && parsed.length > 0 && parsed[0].shots) {
          // Scene-grouped format — flatten shots and inherit scene description
          shotList = parsed.flatMap((scene: { sceneDescription?: string; shots?: ParsedShot[] }) =>
            (scene.shots || []).map((s) => ({
              ...s,
              sceneDescription: s.sceneDescription || scene.sceneDescription || "",
            }))
          );
        } else if (Array.isArray(parsed)) {
          shotList = parsed;
        } else {
          shotList = parsed.shots || [];
        }
        console.log(`[ShotSplit] Chunk ${idx + 1}/${sceneChunks.length}: ${shotList.length} shots, keys: ${shotList[0] ? Object.keys(shotList[0]).join(",") : "empty"}`);
        return shotList as ParsedShot[];
      } catch (err) {
        console.error(`[ShotSplit] Chunk ${idx + 1} failed:`, err);
        // Retry once on parse failure with error feedback
        if (err instanceof SyntaxError) {
          console.log(`[ShotSplit] Chunk ${idx + 1} retrying with error context...`);
          try {
            const retryResult = await generateText({
              model,
              system: systemPrompt + `\n\n【重要】上一次输出的JSON解析失败：${String(err).slice(0, 300)}\n请确保输出严格合法的JSON，特别注意字符串内的引号必须转义，不要出现裸换行。`,
              prompt,
              providerOptions: jsonMode,
            });
            const retryParsed = parseLLMJSON(retryResult.text);
            let retryList: ParsedShot[];
            if (Array.isArray(retryParsed) && retryParsed.length > 0 && retryParsed[0].shots) {
              retryList = retryParsed.flatMap((scene: { sceneDescription?: string; shots?: ParsedShot[] }) =>
                (scene.shots || []).map((s) => ({ ...s, sceneDescription: s.sceneDescription || scene.sceneDescription || "" }))
              );
            } else if (Array.isArray(retryParsed)) {
              retryList = retryParsed;
            } else {
              retryList = retryParsed.shots || [];
            }
            console.log(`[ShotSplit] Chunk ${idx + 1} retry OK: ${retryList.length} shots`);
            return retryList as ParsedShot[];
          } catch (retryErr) {
            console.error(`[ShotSplit] Chunk ${idx + 1} retry also failed:`, retryErr);
          }
        }
        return [] as ParsedShot[];
      }
    })
  );

  // Merge and re-sequence
  const allShots = chunkResults.flat();
  allShots.forEach((s, i) => { s.sequence = i + 1; });

  if (allShots.length === 0) {
    return NextResponse.json({ error: "Failed to generate shots" }, { status: 500 });
  }

  // Create version record
  const versionWhereClause = episodeId
    ? and(eq(storyboardVersions.projectId, projectId), eq(storyboardVersions.episodeId, episodeId))
    : eq(storyboardVersions.projectId, projectId);
  const [maxVersionRow] = await db
    .select({ maxNum: storyboardVersions.versionNum })
    .from(storyboardVersions)
    .where(versionWhereClause)
    .orderBy(desc(storyboardVersions.versionNum))
    .limit(1);
  const nextVersionNum = (maxVersionRow?.maxNum ?? 0) + 1;
  const today = new Date();
  const dateStr = today.getUTCFullYear().toString() +
    String(today.getUTCMonth() + 1).padStart(2, "0") +
    String(today.getUTCDate()).padStart(2, "0");
  const versionLabel = `${dateStr}-V${nextVersionNum}`;
  const versionId = genId();
  await db.insert(storyboardVersions).values({
    id: versionId,
    projectId,
    label: versionLabel,
    versionNum: nextVersionNum,
    createdAt: new Date(),
    episodeId: episodeId ?? null,
  });

  for (const shot of allShots) {
    const shotId = genId();
    await db.insert(shots).values({
      id: shotId,
      projectId,
      versionId,
      sequence: shot.sequence,
      prompt: shot.sceneDescription,
      motionScript: shot.motionScript,
      videoScript: shot.videoScript ?? null,
      cameraDirection: shot.cameraDirection || "static",
      duration: shot.duration,
      transitionIn: shot.transitionIn || "cut",
      transitionOut: shot.transitionOut || "cut",
      compositionGuide: shot.compositionGuide || "",
      focalPoint: shot.focalPoint || "",
      depthOfField: shot.depthOfField || "medium",
      soundDesign: shot.soundDesign || "",
      musicCue: shot.musicCue || "",
      episodeId: episodeId ?? null,
    });
    // No automatic asset seeding — shot_assets rows are only created when
    // the user explicitly clicks "生成首尾帧提示词" or "生成参考图提示词".
    // Each generation button writes only its own asset type.

    for (let i = 0; i < (shot.dialogues || []).length; i++) {
      const dialogue = shot.dialogues[i];
      const matchedChar = shotCharacters.find(
        (c: typeof characters.$inferSelect) => c.name === dialogue.character
      );
      if (matchedChar) {
        await db.insert(dialogues).values({
          id: genId(),
          shotId,
          characterId: matchedChar.id,
          text: dialogue.text,
          sequence: i,
        });
      }
    }
  }

  // Auto-create missing guest characters from shot scene descriptions
  if (episodeId) {
    // Blacklist: generic crowd/scene terms that are not real characters
    const CROWD_BLACKLIST = new Set([
      "士兵", "路人", "百姓", "尸体", "群演", "太监", "宫女", "侍女",
      "小贩", "商贩", "乞丐", "僧侣", "道士", "骑士", "守卫", "门卫",
      "仆从", "丫鬟", "家丁", "侍卫", "随从", "使者", "信使", "难民",
    ]);
    // Hint quality check: must contain at least one concrete visual descriptor
    // (body part, color, texture, clothing), not just transient states
    const VISUAL_HINT_PATTERN = /[体型体态态面相面容脸眼眉鼻嘴唇发须胡服饰衣袍甲冠色肤]/;

    const charPattern = /([\u4e00-\u9fa5a-zA-Z]{1,6})[（(]([^）)]{1,10})[）)]/g;
    const foundChars = new Map<string, { hint: string; contexts: string[]; shotCount: number }>();
    for (const shot of allShots) {
      const desc = shot.sceneDescription || "";
      const sentences = desc.split(/[。！？；]+/).filter((s) => s.trim());
      let match;
      while ((match = charPattern.exec(desc)) !== null) {
        const base = match[1];
        const hint = match[2];
        // Filter 1: skip blacklisted crowd terms
        if (CROWD_BLACKLIST.has(base)) continue;
        // Filter 2: skip hints that are only transient states, not visual descriptors
        if (!VISUAL_HINT_PATTERN.test(hint)) continue;

        if (!foundChars.has(base)) foundChars.set(base, { hint, contexts: [], shotCount: 0 });
        const entry = foundChars.get(base)!;
        entry.shotCount++;
        // Collect unique sentences containing this character
        for (const s of sentences) {
          if (s.includes(match[0]) && !entry.contexts.includes(s.trim())) {
            entry.contexts.push(s.trim());
          }
        }
      }
    }

    // Filter 3: must appear in at least 2 shots to be a real character
    const qualifyingChars = [...foundChars.entries()].filter(([, v]) => v.shotCount >= 2);

    const existingNames = new Set(shotCharacters.map((c) => c.name));
    const existingBaseNames = new Set(shotCharacters.map((c) => stripCharHint(c.name)));
    const missingEntries = qualifyingChars.filter(([base]) =>
      !existingNames.has(base) && !existingBaseNames.has(base)
    );
    if (missingEntries.length > 0) {
      console.log(`[ShotSplit] Generating ${missingEntries.length} guest characters via LLM: ${missingEntries.map(([n]) => n).join(", ")}`);

      // Fetch EP context for the prompt
      const [ep] = await db.select({
        title: episodes.title, description: episodes.description, idea: episodes.idea
      }).from(episodes).where(eq(episodes.id, episodeId));

      // Build bulk prompt for all missing characters
      let bulkPrompt = `${ep?.title || ""}\n构思: ${ep?.idea || "（无）"}\n描述: ${ep?.description || "（无）"}\n\n=== 需要补充外观描述的角色（均为本集客串角色，scope="guest"）===\n`;
      for (const [base, { hint, contexts }] of missingEntries) {
        bulkPrompt += `\n角色名: ${base}\n已有外观线索: ${hint}\n出场场景:\n`;
        for (const ctx of contexts.slice(0, 3)) {
          bulkPrompt += `  - ${ctx}\n`;
        }
      }
      bulkPrompt += "\n请为以上每个角色生成完整的 visualHint（2-4字）和 description（单段密集角色外观描写，含体态/面部/发型/服装/标志特征）。返回 JSON 数组。";

      try {
        if (!modelConfig?.text) {
          console.warn("[ShotSplit] No text model — skipping guest character generation");
        } else {
          const model = createLanguageModel(modelConfig.text);
          const charSystem = await resolvePrompt("character_extract", { userId, projectId }).catch(() => undefined);
          const { text } = await generateText({
            model,
            system: charSystem || "你是角色设计师，生成角色视觉描述。仅返回JSON。",
            prompt: bulkPrompt,
          });
          const parsed = parseLLMJSON(text);
          const chars: Array<{ name: string; visualHint?: string; description: string }> = Array.isArray(parsed) ? parsed : (parsed.characters || []);
          for (const c of chars) {
            const charId = genId();
            await db.insert(characters).values({
              id: charId, projectId,
              baseName: c.name, name: c.name,
              description: c.description || "",
              visualHint: c.visualHint || "",
              scope: "guest", episodeId,
            });
            await db.insert(episodeCharacters).values({
              id: genId(), episodeId, characterId: charId,
            });
            console.log(`[ShotSplit] Created guest character: ${c.name}`);
          }
        }
      } catch (err) {
        console.error("[ShotSplit] Guest character generation failed:", err);
      }
    }
  }

  console.log(`[ShotSplit] Created ${allShots.length} shots from ${sceneChunks.length} chunks`);
  return NextResponse.json({ shots: allShots.length });
}

/** Split screenplay text into chunks by SCENE markers, ~maxScenes per chunk.
 *  Preserves the header (VISUAL STYLE + CHARACTERS) and prepends it to every chunk. */
function splitScriptByScenes(script: string, maxScenes: number): string[] {
  // Match SCENE markers with optional markdown bold (**), whitespace, or other decorators
  const scenePattern = /^[\s*#]*(?:SCENE|场景)\s*\d+/i;
  const lines = script.split("\n");

  // Find scene boundary line indices
  const boundaries: number[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (scenePattern.test(lines[i].trim())) {
      boundaries.push(i);
    }
  }

  // If no scene markers found or few scenes, return as single chunk
  if (boundaries.length <= maxScenes) {
    return [script];
  }

  // Everything before the first SCENE marker is the header (VISUAL STYLE + CHARACTERS)
  const header = lines.slice(0, boundaries[0]).join("\n").trim();

  // Group scenes into chunks, prepend header to each
  const chunks: string[] = [];
  for (let i = 0; i < boundaries.length; i += maxScenes) {
    const start = boundaries[i];
    const end = i + maxScenes < boundaries.length
      ? boundaries[i + maxScenes]
      : lines.length;
    const scenesText = lines.slice(start, end).join("\n");
    chunks.push(header ? `${header}\n\n${scenesText}` : scenesText);
  }

  return chunks;
}

// --- single_shot_rewrite: regenerate text fields for one shot ---

async function handleSingleShotRewrite(
  projectId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  const shotId = payload?.shotId as string;
  if (!shotId) {
    return NextResponse.json({ error: "No shotId provided" }, { status: 400 });
  }
  if (!modelConfig?.text) {
    return NextResponse.json({ error: "No text model configured" }, { status: 400 });
  }

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) {
    return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  }
  const shotView = await loadShotLegacyView(shot.id);

  const shotEpisodeId = episodeId || shot.episodeId;
  const projectCharacters = await getEpisodeCharacters(projectId, shotEpisodeId);
  const characterDescriptions = projectCharacters
    .map((c) => `${c.name}: ${c.description}`)
    .join("\n");
  const characterVisualHints = projectCharacters
    .filter((c) => c.visualHint)
    .map((c) => `${c.name}：${c.visualHint}`)
    .join("\n");

  const model = createLanguageModel(modelConfig.text);

  const prompt = `You are a storyboard director. Rewrite the text fields for a single shot so the descriptions are vivid, safe for AI image generation, and free of any potentially sensitive content.

Current shot (sequence ${shot.sequence}):
- Scene description: ${shot.prompt || ""}
- Start frame: ${shotView.startFrameDesc || ""}
- End frame: ${shotView.endFrameDesc || ""}
- Motion script: ${shot.motionScript || ""}
- Video script: ${shot.videoScript || ""}
- Camera direction: ${shot.cameraDirection || "static"}
- Duration: ${shot.duration}s

Character references:
${characterDescriptions || "none"}
${characterVisualHints ? `\nCHARACTER VISUAL IDs (MANDATORY — whenever a character appears in any field, write their name followed by exactly this identifier in parentheses, e.g. 天枢真君（银发金瞳）. Never invent alternatives):\n${characterVisualHints}` : ""}

Return ONLY a JSON object (no markdown fences) with these fields:
{
  "prompt": "rewritten scene description",
  "startFrameDesc": "rewritten start frame description",
  "endFrameDesc": "rewritten end frame description",
  "motionScript": "rewritten motion script in time-segmented format (0-Xs: ... Xs-Ys: ...)",
  "videoScript": "rewritten concise video model prompt: 1-2 sentences, no timestamps, just core motion and camera arc",
  "cameraDirection": "camera direction (keep original or adjust)"
}

IMPORTANT: Keep the same scene, characters, and narrative intent. Only rephrase to avoid safety filter triggers. Match the language of the original text.`;

  console.log(`[SingleShotRewrite] Shot ${shot.sequence} prompt:\n${prompt}`);

  try {
    const { text } = await import("ai").then(({ generateText }) =>
      generateText({ model, prompt, temperature: 0.7 })
    );

    const parsed = JSON.parse(extractJSON(text)) as {
      prompt: string;
      startFrameDesc: string;
      endFrameDesc: string;
      motionScript: string;
      videoScript?: string;
      cameraDirection: string;
    };

    await db
      .update(shots)
      .set({
        prompt: parsed.prompt,
        motionScript: parsed.motionScript,
        videoScript: parsed.videoScript ?? null,
        cameraDirection: parsed.cameraDirection,
      })
      .where(eq(shots.id, shotId));
    // Update first/last frame prompts in shot_assets
    {
      const ff = await getActiveAsset(shotId, "first_frame", 0);
      if (ff) {
        await patchAsset(ff.id, { prompt: parsed.startFrameDesc });
      } else {
        await insertAssetVersion({
          shotId, type: "first_frame", sequenceInType: 0,
          prompt: parsed.startFrameDesc, status: "pending",
        });
      }
      const lf = await getActiveAsset(shotId, "last_frame", 0);
      if (lf) {
        await patchAsset(lf.id, { prompt: parsed.endFrameDesc });
      } else {
        await insertAssetVersion({
          shotId, type: "last_frame", sequenceInType: 0,
          prompt: parsed.endFrameDesc, status: "pending",
        });
      }
    }

    return NextResponse.json({ shotId, status: "ok", ...parsed });
  } catch (err) {
    console.error(`[SingleShotRewrite] Error for shot ${shotId}:`, err);
    return NextResponse.json({ shotId, status: "error", error: extractErrorMessage(err) }, { status: 500 });
  }
}

// --- batch_frame_generate: sequential frame generation with continuity chain ---

async function handleBatchFrameGenerate(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  if (!modelConfig?.image) {
    return NextResponse.json(
      { error: "No image model configured" },
      { status: 400 }
    );
  }

  let batchVersionId = payload?.versionId as string | undefined;
  if (!batchVersionId) {
    const [latestVer] = await db.select({ id: storyboardVersions.id })
      .from(storyboardVersions)
      .where(and(
        eq(storyboardVersions.projectId, projectId),
        ...(episodeId ? [eq(storyboardVersions.episodeId, episodeId)] : [])
      ))
      .orderBy(desc(storyboardVersions.versionNum))
      .limit(1);
    if (!latestVer?.id) return NextResponse.json({ error: "No version found. Run shot split first." }, { status: 400 });
    batchVersionId = latestVer.id;
  }
  const imageOpts = { size: ratioToSize(payload?.ratio as string), aspectRatio: (payload?.ratio as string) || "16:9" };
  const shotWhereConditions = [eq(shots.projectId, projectId)];
  if (batchVersionId) shotWhereConditions.push(eq(shots.versionId, batchVersionId));
  if (episodeId) shotWhereConditions.push(eq(shots.episodeId, episodeId));
  const allShots = await db
    .select()
    .from(shots)
    .where(and(...shotWhereConditions))
    .orderBy(asc(shots.sequence));

  if (allShots.length === 0) {
    return NextResponse.json({ results: [], message: "No shots found" });
  }
  const allShotsLegacy = await loadShotLegacyViewsBatch(allShots.map((s) => s.id));

  const versionedUploadDir = batchVersionId
    ? await getVersionedUploadDir(batchVersionId)
    : getUploadDir();

  // Fetch only characters linked to this episode
  let frameCharacters: typeof characters.$inferSelect[];
  if (episodeId) {
    const linkedIds = await db
      .select({ characterId: episodeCharacters.characterId })
      .from(episodeCharacters)
      .where(eq(episodeCharacters.episodeId, episodeId));
    frameCharacters = linkedIds.length > 0
      ? await db.select().from(characters).where(inArray(characters.id, linkedIds.map((r) => r.characterId)))
      : [];
  } else {
    frameCharacters = await db.select().from(characters).where(eq(characters.projectId, projectId));
  }

  const characterDescriptions = frameCharacters
    .map((c) => `${c.name}: ${c.description}`)
    .join("\n");

  const charsWithImages = frameCharacters.filter((c) => c.referenceImage);

  const ai = resolveImageProvider(modelConfig, versionedUploadDir);
  const results: Array<{ shotId: string; sequence: number; status: string; firstFrame?: string; lastFrame?: string; error?: string }> = [];

  const overwrite = payload?.overwrite === true;
  const needProcess = allShots.filter((s) => {
    const v = allShotsLegacy.get(s.id);
    return overwrite || !v?.firstFrame || !v?.lastFrame;
  });
  const skipCount = allShots.length - needProcess.length;

  console.log(`[BatchFrameGenerate] Total: ${allShots.length} shots, need: ${needProcess.length}, skip: ${skipCount}, characters: ${frameCharacters.length}`);

  const frameFirstSlots = await resolveSlotContents("frame_generate_first", { userId, projectId });
  const frameLastSlots = await resolveSlotContents("frame_generate_last", { userId, projectId });

  // ── Sequential per-shot generation ──
  // Process shots one at a time so each completion is immediately
  // persisted to DB. If the process is interrupted, previously
  // completed shots remain saved and can be skipped on retry.
  const total = allShots.length;
  let doneCount = 0;
  console.log(`[BatchFrameGenerate] Starting sequential generation: 0/${total}`);

  for (const shot of allShots) {
    const shotLegacy = allShotsLegacy.get(shot.id);

    if (!overwrite && shotLegacy?.firstFrame && shotLegacy?.lastFrame) {
      doneCount++;
      console.log(`[BatchFrameGenerate] ⊙ shot ${shot.sequence} skipped (${doneCount}/${total})`);
      results.push({ shotId: shot.id, sequence: shot.sequence, status: "skipped" });
      continue;
    }

    const startTime = Date.now();
    try {
      await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shot.id));

      const ffAssetExisting = await getActiveAsset(shot.id, "first_frame", 0);
      const lfAssetExisting = await getActiveAsset(shot.id, "last_frame", 0);
      const shotCharNameSet = new Set<string>([
        ...(ffAssetExisting?.characters ?? []).map(stripCharHint),
        ...(lfAssetExisting?.characters ?? []).map(stripCharHint),
      ]);
      const filteredChars = shotCharNameSet.size > 0
        ? charsWithImages.filter((c) => shotCharNameSet.has(stripCharHint(c.name)) || shotCharNameSet.has((c as any).baseName || ""))
        : [];
      const shotCharRefImages = filteredChars.map((c) => c.referenceImage!);
      const shotCharRefLabels = filteredChars.map((c) => c.name);
      const shotCharsForPersist = filteredChars.length > 0 ? filteredChars.map((c) => c.name) : undefined;

      const ffAsset = await getLatestCompletedAsset(shot.id, "first_frame")
        || await getActiveAsset(shot.id, "first_frame", 0);
      const lfAsset = await getLatestCompletedAsset(shot.id, "last_frame")
        || await getActiveAsset(shot.id, "last_frame", 0);
      const startFrameText = ffAsset?.prompt || shotLegacy?.startFrameDesc || shot.prompt || "";
      const endFrameText = lfAsset?.prompt || shotLegacy?.endFrameDesc || shot.prompt || "";

      const firstPrompt = buildFirstFramePrompt({
        sceneDescription: shot.prompt || "",
        startFrameDesc: startFrameText,
        characterDescriptions: "",
        slotContents: frameFirstSlots,
      });
      const firstFramePath = await ai.generateImage(firstPrompt, {
        ...imageOpts,
        quality: "hd",
        referenceImages: shotCharRefImages,
        referenceLabels: shotCharRefLabels,
        scenePrompt: shot.prompt || "",
      });

      const lastPrompt = buildLastFramePrompt({
        sceneDescription: shot.prompt || "",
        endFrameDesc: endFrameText,
        characterDescriptions: "",
        firstFramePath,
        slotContents: frameLastSlots,
      });
      const lastFramePath = await ai.generateImage(lastPrompt, {
        ...imageOpts,
        quality: "hd",
        referenceImages: shotCharRefImages,
        referenceLabels: shotCharRefLabels,
        scenePrompt: shot.prompt || "",
      });

      // Persist immediately — survives process interruption
      await db.update(shots).set({ status: "completed" }).where(eq(shots.id, shot.id));

      if (ffAssetExisting) await patchAsset(ffAssetExisting.id, { fileUrl: firstFramePath, status: "completed" });
      else
        await insertAssetVersion({
          shotId: shot.id, type: "first_frame", sequenceInType: 0,
          prompt: shotLegacy?.startFrameDesc ?? "", fileUrl: firstFramePath, status: "completed", characters: shotCharsForPersist,
        });
      if (lfAssetExisting) await patchAsset(lfAssetExisting.id, { fileUrl: lastFramePath, status: "completed" });
      else
        await insertAssetVersion({
          shotId: shot.id, type: "last_frame", sequenceInType: 0,
          prompt: shotLegacy?.endFrameDesc ?? "", fileUrl: lastFramePath, status: "completed", characters: shotCharsForPersist,
        });

      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      doneCount++;
      console.log(`[BatchFrameGenerate] ✓ shot ${shot.sequence} (${doneCount}/${total}) ${elapsed}s`);

      results.push({ shotId: shot.id, sequence: shot.sequence, status: "ok", firstFrame: firstFramePath, lastFrame: lastFramePath });
    } catch (err) {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      doneCount++;
      console.error(`[BatchFrameGenerate] ✗ shot ${shot.sequence} (${doneCount}/${total}) ${elapsed}s:`, err);
      await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shot.id));
      results.push({ shotId: shot.id, sequence: shot.sequence, status: "error", error: extractErrorMessage(err) });
    }
  }

  const okCount = results.filter((r) => r.status === "ok").length;
  const errCount = results.filter((r) => r.status === "error").length;
  console.log(`[BatchFrameGenerate] Done: ${okCount} ok, ${errCount} errors, ${skipCount} skipped`);

  return NextResponse.json({ results });
}

// --- single_frame_generate: synchronous frame generation for one shot ---

async function handleSingleFrameGenerate(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  const shotId = payload?.shotId as string;
  if (!shotId) {
    return NextResponse.json({ error: "No shotId provided" }, { status: 400 });
  }
  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) {
    return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  }

  // Read prompts from shot_assets — they were generated by the dedicated
  // "生成首尾帧提示词" step. Each shot is independent: no continuity chain.
  // Use latest completed asset regardless of is_active.
  const ffAsset = await getLatestCompletedAsset(shotId, "first_frame")
    || await getActiveAsset(shotId, "first_frame", 0);
  const lfAsset = await getLatestCompletedAsset(shotId, "last_frame")
    || await getActiveAsset(shotId, "last_frame", 0);
  const startFramePromptText = ffAsset?.prompt || shot.prompt || "";
  const endFramePromptText = lfAsset?.prompt || shot.prompt || "";

  const versionedUploadDir = await getVersionedUploadDir(shot.versionId);
  const shotEpisodeId = episodeId || shot.episodeId;
  const projectCharacters = await getEpisodeCharacters(projectId, shotEpisodeId);

  // Per-shot character filter: only inject refs for characters declared
  // on the first_frame / last_frame asset metadata for this shot.
  const shotCharNameSet = new Set<string>([
    ...(ffAsset?.characters ?? []).map(stripCharHint),
    ...(lfAsset?.characters ?? []).map(stripCharHint),
  ]);
  const filteredChars = shotCharNameSet.size > 0
    ? projectCharacters.filter((c) => c.referenceImage && (shotCharNameSet.has(stripCharHint(c.name)) || shotCharNameSet.has((c as any).baseName || "")))
    : [];
  const shotCharRefImages = filteredChars.map((c) => c.referenceImage as string);

  const ai = resolveImageProvider(modelConfig, versionedUploadDir);
  const imageOpts = { size: ratioToSize(payload?.ratio as string), aspectRatio: (payload?.ratio as string) || "16:9" };

  const frameFirstSlots = await resolveSlotContents("frame_generate_first", { userId, projectId });
  const frameLastSlots = await resolveSlotContents("frame_generate_last", { userId, projectId });

  try {
    await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shotId));

    const firstPrompt = buildFirstFramePrompt({
      sceneDescription: shot.prompt || "",
      startFrameDesc: startFramePromptText,
      characterDescriptions: "",
      slotContents: frameFirstSlots,
    });
    const firstFramePath = await ai.generateImage(firstPrompt, {
      ...imageOpts,
      quality: "hd",
      referenceImages: shotCharRefImages,
      scenePrompt: shot.prompt || "",
    });

    const lastPrompt = buildLastFramePrompt({
      sceneDescription: shot.prompt || "",
      endFrameDesc: endFramePromptText,
      characterDescriptions: "",
      firstFramePath,
      slotContents: frameLastSlots,
    });
    const lastFramePath = await ai.generateImage(lastPrompt, {
      ...imageOpts,
      quality: "hd",
      referenceImages: shotCharRefImages,
      scenePrompt: shot.prompt || "",
    });

    await db.update(shots).set({ status: "completed" }).where(eq(shots.id, shotId));

    if (ffAsset) await patchAsset(ffAsset.id, { fileUrl: firstFramePath, status: "completed" });
    else
      await insertAssetVersion({
        shotId,
        type: "first_frame",
        sequenceInType: 0,
        prompt: startFramePromptText,
        fileUrl: firstFramePath,
        status: "completed",
      });
    if (lfAsset) await patchAsset(lfAsset.id, { fileUrl: lastFramePath, status: "completed" });
    else
      await insertAssetVersion({
        shotId,
        type: "last_frame",
        sequenceInType: 0,
        prompt: endFramePromptText,
        fileUrl: lastFramePath,
        status: "completed",
      });

    return NextResponse.json({ shotId, firstFrame: firstFramePath, lastFrame: lastFramePath, status: "ok" });
  } catch (err) {
    console.error(`[SingleFrameGenerate] Error for shot ${shotId}:`, err);
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shotId));
    return NextResponse.json({ shotId, status: "error", error: extractErrorMessage(err) }, { status: 500 });
  }
}

// --- single_video_generate: synchronous video generation for one shot ---

async function handleSingleVideoGenerate(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const shotId = payload?.shotId as string;
  if (!shotId) {
    return NextResponse.json({ error: "No shotId provided" }, { status: 400 });
  }
  if (!modelConfig?.video) {
    return NextResponse.json({ error: "No video model configured" }, { status: 400 });
  }

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) {
    return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  }
  const shotView = await loadShotLegacyView(shot.id);
  if (!shotView.firstFrame || !shotView.lastFrame) {
    return NextResponse.json({ error: "Shot frames not generated yet" }, { status: 400 });
  }

  const versionedUploadDir = await getVersionedUploadDir(shot.versionId);

  const shotCharacters = await db
    .select()
    .from(characters)
    .where(eq(characters.projectId, shot.projectId));
  const characterDescriptions = shotCharacters
    .map((c) => `${c.name}${c.visualHint ? `（${c.visualHint}）` : ""}: ${c.description}`)
    .join("\n");

  const shotDialogues = await db
    .select({ text: dialogues.text, characterId: dialogues.characterId, sequence: dialogues.sequence })
    .from(dialogues)
    .where(eq(dialogues.shotId, shotId))
    .orderBy(asc(dialogues.sequence));

  const videoProvider = resolveVideoProvider(modelConfig, versionedUploadDir);
  const videoSlots = await resolveSlotContents("video_generate", { userId, projectId });

  try {
    await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shotId));

    const ratio = (payload?.ratio as string) || "16:9";

    const videoModelId = modelConfig?.video?.modelId;
    const videoMaxDuration = getModelMaxDuration(videoModelId);
    const effectiveDuration = Math.min(shot.duration ?? 10, videoMaxDuration);

    const videoScript = shot.videoScript || shot.motionScript || shot.prompt || "";
    const videoContextForDialogue = videoScript;
    const onScreenDialogueChars = shotDialogues
      .map((d) => shotCharacters.find((c) => c.id === d.characterId)?.name ?? "Unknown")
      .filter((name) => isCharacterOnScreen(name, videoContextForDialogue, shotView.startFrameDesc));

    const dialogueList = shotDialogues.map((d) => {
      const char = shotCharacters.find((c) => c.id === d.characterId);
      const characterName = char?.name ?? "Unknown";
      const onScreen = isCharacterOnScreen(characterName, videoContextForDialogue, shotView.startFrameDesc);
      const visualHint = onScreen ? (char?.visualHint || undefined) : undefined;
      return {
        characterName,
        text: d.text,
        offscreen: !onScreen,
        visualHint,
      };
    });
    const textProvider = resolveAIProvider(modelConfig);
    const useH3VP = process.env.H3_PROMPT_MODE !== "seedance";
    let videoPrompt: string;
    if (shot.videoPrompt) {
      videoPrompt = shot.videoPrompt;
    } else if (useH3VP) {
      const { buildVideoPromptLLM: buildH3 } = await import("@/lib/ai/prompts/h3");
      const h3System = await resolvePrompt("video_h3_prompt", { userId, projectId }).catch(() => undefined);
      const h3Lang = (process.env.H3_LANGUAGE as "zh" | "en" | undefined) || "zh";
      const h3Output = await buildH3({
        videoScript,
        motionScript: shot.motionScript,
        duration: effectiveDuration,
        cameraDirection: shot.cameraDirection || "static",
        generationMode: (shot.episodeId
          ? (await db.select({ gm: episodes.generationMode }).from(episodes).where(eq(episodes.id, shot.episodeId)))?.[0]?.gm
          : (await db.select({ gm: projects.generationMode }).from(projects).where(eq(projects.id, projectId)))?.[0]?.gm) as "keyframe" | "reference" || "keyframe",
        characters: shotCharacters.map(c => ({ id: c.id, name: c.name, description: c.description, visualHint: c.visualHint, referenceImage: c.referenceImage, performanceStyle: c.performanceStyle, scope: c.scope, heightCm: c.heightCm, bodyType: c.bodyType })),
        firstFrame: { fileUrl: shotView.firstFrame || "", prompt: shotView.startFrameDesc },
        lastFrame: { fileUrl: shotView.lastFrame || "", prompt: shotView.endFrameDesc },
        soundDesign: shot.soundDesign || undefined,
        musicCue: shot.musicCue || undefined,
        languageMode: h3Lang,
        dialogues: undefined,
            // TODO: load per-shot dialogues for batch H3
      }, textProvider, h3System);
      videoPrompt = h3Output.sections.join("\n\n");
    } else {
      videoPrompt = buildVideoPrompt({
        videoScript,
        cameraDirection: shot.cameraDirection || "static",
        motionScript: shot.motionScript,
        startFrameDesc: shotView.startFrameDesc ?? undefined,
        endFrameDesc: shotView.endFrameDesc ?? undefined,
        duration: effectiveDuration,
        characters: shotCharacters,
        dialogues: undefined,
            // TODO: load per-shot dialogues for batch H3
        slotContents: videoSlots,
      });
    }

    const result = await videoProvider.generateVideo({
      firstFrame: shotView.firstFrame,
      lastFrame: shotView.lastFrame,
      prompt: videoPrompt,
      duration: effectiveDuration,
      ratio,
    });

    // Track video history via shot_assets keyframe_video slot
    await insertAssetVersion({
      shotId, type: "keyframe_video", sequenceInType: 0,
      prompt: videoPrompt, fileUrl: result.filePath, status: "completed",
    });

    await db
      .update(shots)
      .set({ status: "completed" })
      .where(eq(shots.id, shotId));

    return NextResponse.json({ shotId, videoUrl: result.filePath, status: "ok" });
  } catch (err) {
    console.error(`[SingleVideoGenerate] Error for shot ${shotId}:`, err);
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shotId));
    return NextResponse.json({ shotId, status: "error", error: extractErrorMessage(err) }, { status: 500 });
  }
}

// --- batch_video_generate: sequential video generation for all eligible shots ---

async function handleBatchVideoGenerate(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  if (!modelConfig?.video) {
    return NextResponse.json({ error: "No video model configured" }, { status: 400 });
  }

  let batchVersionId = payload?.versionId as string | undefined;
  if (!batchVersionId) {
    const [latestVer] = await db.select({ id: storyboardVersions.id })
      .from(storyboardVersions)
      .where(and(
        eq(storyboardVersions.projectId, projectId),
        ...(episodeId ? [eq(storyboardVersions.episodeId, episodeId)] : [])
      ))
      .orderBy(desc(storyboardVersions.versionNum))
      .limit(1);
    if (!latestVer?.id) return NextResponse.json({ error: "No version found. Run shot split first." }, { status: 400 });
    batchVersionId = latestVer.id;
  }
  const shotWhereConditions = [eq(shots.projectId, projectId)];
  if (batchVersionId) shotWhereConditions.push(eq(shots.versionId, batchVersionId));
  if (episodeId) shotWhereConditions.push(eq(shots.episodeId, episodeId));
  const allShots = await db
    .select()
    .from(shots)
    .where(and(...shotWhereConditions))
    .orderBy(asc(shots.sequence));

  const versionedUploadDir = batchVersionId
    ? await getVersionedUploadDir(batchVersionId)
    : getUploadDir();

  const overwrite = payload?.overwrite === true;
  const allShotsLegacy = await loadShotLegacyViewsBatch(allShots.map((s) => s.id));
  const eligible = allShots.filter((s) => {
    const v = allShotsLegacy.get(s.id);
    return v?.firstFrame && v?.lastFrame && (overwrite || !v?.videoUrl);
  });
  if (eligible.length === 0) {
    return NextResponse.json({ results: [], message: "No eligible shots" });
  }

  const batchCharacters = await getEpisodeCharacters(projectId, episodeId);
  const characterDescriptions = batchCharacters
    .map((c) => `${c.name}: ${c.description}`)
    .join("\n");

  const videoProvider = resolveVideoProvider(modelConfig, versionedUploadDir);
  const ratio = (payload?.ratio as string) || "16:9";
  const videoMaxDuration = getModelMaxDuration(modelConfig?.video?.modelId);
  const videoSlots = await resolveSlotContents("video_generate", { userId, projectId });

  // Generation mode for H3 prompt builder
  let batchGenMode: "keyframe" | "reference" = "keyframe";
  if (episodeId) {
    const [ep] = await db.select({ gm: episodes.generationMode }).from(episodes).where(eq(episodes.id, episodeId));
    batchGenMode = (ep?.gm as "keyframe" | "reference") || "keyframe";
  } else {
    const [proj] = await db.select({ gm: projects.generationMode }).from(projects).where(eq(projects.id, projectId));
    batchGenMode = (proj?.gm as "keyframe" | "reference") || "keyframe";
  }

  // ── Sequential per-shot generation ──
  // Process shots one at a time with immediate DB persistence.
  const total = eligible.length;
  let doneCount = 0;
  console.log(`[BatchVideoGenerate] Starting sequential generation: 0/${total}`);

  const results: Array<{ shotId: string; sequence: number; status: string; videoUrl?: string; error?: string }> = [];

  for (const shot of eligible) {
    const startTime = Date.now();
    try {
      await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shot.id));

      const shotLegacy = allShotsLegacy.get(shot.id);
      const effectiveDuration = Math.min(shot.duration ?? 10, videoMaxDuration);
      const shotDialogues = await db
        .select({ text: dialogues.text, characterId: dialogues.characterId, sequence: dialogues.sequence })
        .from(dialogues)
        .where(eq(dialogues.shotId, shot.id))
        .orderBy(asc(dialogues.sequence));

      const videoScript = shot.videoScript || shot.motionScript || shot.prompt || "";
      const videoContextForDialogue = videoScript;
      const onScreenDialogueChars = shotDialogues
        .map((d) => batchCharacters.find((c) => c.id === d.characterId)?.name ?? "Unknown")
        .filter((name) => isCharacterOnScreen(name, videoContextForDialogue, shotLegacy?.startFrameDesc ?? null));

      const dialogueList = shotDialogues.map((d) => {
        const char = batchCharacters.find((c) => c.id === d.characterId);
        const characterName = char?.name ?? "Unknown";
        const onScreen = isCharacterOnScreen(characterName, videoContextForDialogue, shotLegacy?.startFrameDesc ?? null);
        const visualHint = onScreen ? (char?.visualHint || undefined) : undefined;
        return { characterName, text: d.text, offscreen: !onScreen, visualHint };
      });

      const textProvider = resolveAIProvider(modelConfig);
      const useH3VG = process.env.H3_PROMPT_MODE !== "seedance";
      let videoPrompt: string;
      if (shot.videoPrompt) {
        videoPrompt = shot.videoPrompt;
      } else if (useH3VG) {
        const { buildVideoPromptLLM: buildH3 } = await import("@/lib/ai/prompts/h3");
        const h3System = await resolvePrompt("video_h3_prompt", { userId, projectId }).catch(() => undefined);
        const h3Lang = (process.env.H3_LANGUAGE as "zh" | "en" | undefined) || "zh";
        const h3Output = await buildH3({
          videoScript,
          motionScript: shot.motionScript,
          duration: effectiveDuration,
          cameraDirection: shot.cameraDirection || "static",
          generationMode: batchGenMode as "keyframe" | "reference",
          characters: batchCharacters.map(c => ({ id: c.id, name: c.name, description: c.description, visualHint: c.visualHint, referenceImage: c.referenceImage, performanceStyle: c.performanceStyle, scope: c.scope, heightCm: c.heightCm, bodyType: c.bodyType })),
          firstFrame: { fileUrl: shotLegacy?.firstFrame || "", prompt: shotLegacy?.startFrameDesc },
          lastFrame: { fileUrl: shotLegacy?.lastFrame || "", prompt: shotLegacy?.endFrameDesc },
          soundDesign: shot.soundDesign || undefined,
          musicCue: shot.musicCue || undefined,
          languageMode: h3Lang,
        }, textProvider, h3System);
        videoPrompt = h3Output.sections.join("\n\n");
      } else {
        videoPrompt = buildVideoPrompt({
          videoScript,
          cameraDirection: shot.cameraDirection || "static",
          motionScript: shot.motionScript,
          startFrameDesc: shotLegacy?.startFrameDesc ?? undefined,
          endFrameDesc: shotLegacy?.endFrameDesc ?? undefined,
          duration: effectiveDuration,
          characters: batchCharacters,
          dialogues: undefined,
            // TODO: load per-shot dialogues for batch H3
          slotContents: videoSlots,
        });
      }

      const genResult = await videoProvider.generateVideo({
        firstFrame: shotLegacy!.firstFrame!,
        lastFrame: shotLegacy!.lastFrame!,
        prompt: videoPrompt,
        duration: effectiveDuration,
        ratio,
      });

      await insertAssetVersion({
        shotId: shot.id, type: "keyframe_video", sequenceInType: 0,
        prompt: videoPrompt, fileUrl: genResult.filePath, status: "completed",
      });
      await db.update(shots).set({ status: "completed" }).where(eq(shots.id, shot.id));

      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      doneCount++;
      console.log(`[BatchVideoGenerate] ✓ shot ${shot.sequence} (${doneCount}/${total}) ${elapsed}s`);

      results.push({ shotId: shot.id, sequence: shot.sequence, status: "ok", videoUrl: genResult.filePath });
    } catch (err) {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      doneCount++;
      console.error(`[BatchVideoGenerate] ✗ shot ${shot.sequence} (${doneCount}/${total}) ${elapsed}s:`, err);
      await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shot.id));
      results.push({ shotId: shot.id, sequence: shot.sequence, status: "error", error: extractErrorMessage(err) });
    }
  }

  return NextResponse.json({ results });
}

// --- single_scene_frame: generate Toonflow-style scene reference frame only ---

async function handleSingleSceneFrame(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const shotId = payload?.shotId as string | undefined;
  if (!shotId) {
    return NextResponse.json({ error: "No shotId provided" }, { status: 400 });
  }
  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) {
    return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  }

  const versionedUploadDir = await getVersionedUploadDir(shot.versionId);

  try {
    await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shotId));

    const imageProvider = resolveImageProvider(modelConfig, versionedUploadDir);
    const slotContents = await resolveSlotContents("scene_frame_generate", { userId, projectId });
    const sceneFrameView = await loadShotLegacyView(shot.id);
    const sceneFramePrompt = buildSceneFramePrompt({
      sceneDescription: shot.prompt || "",
      charRefMapping: "",
      characterDescriptions: "",
      cameraDirection: shot.cameraDirection,
      startFrameDesc: sceneFrameView.startFrameDesc,
      motionScript: shot.motionScript,
      slotContents,
    });

    console.log(`[SingleSceneFrame] Shot ${shot.sequence}: generating scene-only frame (no character refs)`);

    // Scene-only: no character reference images injected.
    const sceneFramePath = await imageProvider.generateImage(sceneFramePrompt, {
      quality: "hd",
    });

    {
      const refEx = await getActiveAsset(shotId, "reference", 0);
      if (refEx) {
        // Preserve pre-existing characters metadata on regeneration.
        await patchAsset(refEx.id, { fileUrl: sceneFramePath, status: "completed" });
      } else {
        // Fresh creation: copy characters from sibling ref assets if any.
        const siblingChars = sceneFrameView.referenceImages[0]?.characters ?? undefined;
        await insertAssetVersion({
          shotId,
          type: "reference",
          sequenceInType: 0,
          prompt: "",
          fileUrl: sceneFramePath,
          status: "completed",
          characters: siblingChars,
        });
      }
    }
    await db
      .update(shots)
      .set({ status: "pending" })
      .where(eq(shots.id, shotId));

    return NextResponse.json({ shotId, sceneRefFrame: sceneFramePath, status: "ok" });
  } catch (err) {
    console.error(`[SingleSceneFrame] Error for shot ${shot.sequence}:`, err);
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shotId));
    return NextResponse.json(
      { shotId, status: "error", error: extractErrorMessage(err) },
      { status: 500 }
    );
  }
}

// --- batch_scene_frame: generate scene reference frames for all eligible shots ---

async function handleBatchSceneFrame(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const overwrite = payload?.overwrite === true;
  const ratio = (payload?.ratio as string) || "16:9";
  const imageOpts = { size: ratioToSize(ratio), aspectRatio: ratio };
  const batchVersionId = payload?.versionId as string | undefined;

  const shotWhereConditions = [eq(shots.projectId, projectId)];
  if (batchVersionId) shotWhereConditions.push(eq(shots.versionId, batchVersionId));
  if (episodeId) shotWhereConditions.push(eq(shots.episodeId, episodeId));
  const allShots = await db.select().from(shots).where(and(...shotWhereConditions)).orderBy(asc(shots.sequence));

  const versionedUploadDir = batchVersionId
    ? await getVersionedUploadDir(batchVersionId)
    : getUploadDir();

  const imageProvider = resolveImageProvider(modelConfig, versionedUploadDir);
  const allShotsLegacy = await loadShotLegacyViewsBatch(allShots.map((s) => s.id));

  // Mark all eligible shots as generating
  const eligible = allShots.filter((shot) => {
    const refImages = allShotsLegacy.get(shot.id)?.referenceImages ?? [];
    const targets = overwrite
      ? refImages.filter((r) => r.prompt.trim())
      : refImages.filter((r) => r.status === "pending" && r.prompt.trim());
    return targets.length > 0;
  });

  await Promise.all(
    eligible.map((shot) => db.update(shots).set({ status: "generating" }).where(eq(shots.id, shot.id)))
  );

  // Process all shots concurrently
  const results = await Promise.all(
    allShots.map(async (shot) => {
      const refImages = allShotsLegacy.get(shot.id)?.referenceImages ?? [];
      const targets = overwrite
        ? refImages.filter((r) => r.prompt.trim())
        : refImages.filter((r) => r.status === "pending" && r.prompt.trim());

      if (targets.length === 0) {
        return { shotId: shot.id, sequence: shot.sequence, status: "ok" as const, generated: 0 };
      }

      console.log(`[BatchSceneFrame] Shot ${shot.sequence}: ${targets.length} scene-only refs (no character injection)`);

      // Generate all ref images for this shot concurrently.
      // Scene-only: NO character reference images passed to the image model.
      // But the per-shot `characters` metadata is preserved so downstream
      // video generation knows which characters belong to this shot.
      const genResults = await Promise.all(
        targets.map(async (entry) => {
          try {
            const imagePath = await imageProvider.generateImage(entry.prompt, {
              quality: "hd",
              ...imageOpts,
            });
            // Persist as a new version of this reference slot
            await insertAssetVersion({
              shotId: shot.id, type: "reference", sequenceInType: entry.sequenceInType,
              prompt: entry.prompt, fileUrl: imagePath, status: "completed",
              characters: entry.characters ?? undefined,
            });
            console.log(`[BatchRefImage] Shot ${shot.sequence}: ref "${entry.id}" done`);
            return true;
          } catch (err) {
            console.warn(`[BatchRefImage] Shot ${shot.sequence} ref ${entry.id} failed:`, err);
            return false;
          }
        })
      );

      const generated = genResults.filter(Boolean).length;

      await db
        .update(shots)
        .set({ status: "pending" })
        .where(eq(shots.id, shot.id));

      return { shotId: shot.id, sequence: shot.sequence, status: "ok" as const, generated };
    })
  );

  return NextResponse.json({ results });
}

// --- single_reference_video: text2video with character reference images ---

async function handleSingleReferenceVideo(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const shotId = payload?.shotId as string | undefined;
  if (!shotId) {
    return NextResponse.json({ error: "No shotId provided" }, { status: 400 });
  }
  if (!modelConfig?.video) {
    return NextResponse.json({ error: "No video model configured" }, { status: 400 });
  }
  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) {
    return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  }
  const shotView = await loadShotLegacyView(shot.id);

  const versionedUploadDir = await getVersionedUploadDir(shot.versionId);

  const projectCharacters = await db
    .select()
    .from(characters)
    .where(eq(characters.projectId, shot.projectId));

  // Collect the union of character names declared on this shot's
  // reference assets — this is the precise set of characters the AI said
  // will act in this shot. Only these get passed to the video model.
  const shotCharNameSet = new Set<string>();
  for (const r of shotView.referenceImages) {
    for (const n of r.characters ?? []) shotCharNameSet.add(stripCharHint(n));
  }

  const charRefs = projectCharacters
    .filter((c) => !!c.referenceImage && (shotCharNameSet.has(stripCharHint(c.name)) || shotCharNameSet.has((c as any).baseName || "")))
    .map((c) => ({ name: c.name, imagePath: c.referenceImage as string }));

  // charRefs may be empty — that's legal for shots with no characters
  // (pure environment / transition shots). Scene-only videos will be
  // generated from scene frames alone.

  // Seedance @ syntax mapping: "@图1是角色A，@图2是角色B"
  const charRefMapping = charRefs.map((c, i) => `@图片${i + 1}是${c.name}`).join("，");

  const characterDescriptions = projectCharacters
    .map((c) => `${c.name}: ${c.description}`)
    .join("\n");

  const shotDialogues = await db
    .select({ text: dialogues.text, characterId: dialogues.characterId, sequence: dialogues.sequence })
    .from(dialogues)
    .where(eq(dialogues.shotId, shotId))
    .orderBy(asc(dialogues.sequence));
  const videoContextForDialogue = shot.motionScript || shot.videoScript || shot.prompt || "";
  const onScreenDialogueChars = shotDialogues
    .map((d) => projectCharacters.find((c) => c.id === d.characterId)?.name ?? "Unknown")
    .filter((name) => isCharacterOnScreen(name, videoContextForDialogue, shotView.startFrameDesc));

  const dialogueList = shotDialogues.map((d) => {
    const char = projectCharacters.find((c) => c.id === d.characterId);
    const characterName = char?.name ?? "Unknown";
    const onScreen = isCharacterOnScreen(characterName, videoContextForDialogue, shotView.startFrameDesc);
    const visualHint = onScreen ? (char?.visualHint || undefined) : undefined;
    return {
      characterName,
      text: d.text,
      offscreen: !onScreen,
      visualHint,
    };
  });

  const ratio = (payload?.ratio as string) || "16:9";
  const refVideoSlots = await resolveSlotContents("ref_video_generate", { userId, projectId });

  try {
    await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shotId));

    // Step 1: Collect scene frames (pure environment) — may be multiple per shot
    //         (e.g. ground → sky transitions in an action beat).
    const sceneFramePaths: string[] = shotView.referenceImages
      .filter((r) => r.fileUrl)
      .sort((a, b) => a.sequenceInType - b.sequenceInType)
      .map((r) => r.fileUrl as string);

    if (sceneFramePaths.length === 0) {
      return NextResponse.json(
        { error: "No scene reference images. Please generate scene reference images first." },
        { status: 400 }
      );
    }

    console.log(`[SingleReferenceVideo] Shot ${shot.sequence}: ${sceneFramePaths.length} scene frame(s), ${charRefs.length} character ref(s)`);

    // Step 2: Build Seedance 2 multi-reference image list.
    //         Order matters — it becomes 图1, 图2, … in the mapping.
    const orderedRefImages: string[] = [
      ...charRefs.map((c) => c.imagePath),
      ...sceneFramePaths,
    ];

    // Build explicit index mapping for the prompt builder
    const characterRefInfos = charRefs.map((c, i) => ({
      name: c.name,
      index: i + 1,
      visualHint: projectCharacters.find((pc) => pc.name === c.name)?.visualHint,
    }));
    const sceneAssetList = shotView.referenceImages
      .filter((r) => r.fileUrl)
      .sort((a, b) => a.sequenceInType - b.sequenceInType);
    const sceneFrameInfos = sceneFramePaths.map((_, i) => {
      const metaObj = sceneAssetList[i]?.meta as { sceneName?: string } | null;
      const name = metaObj?.sceneName || (sceneFramePaths.length > 1 ? `场景-${i + 1}` : `场景`);
      return { label: name, index: charRefs.length + i + 1 };
    });
    const fullMapping = [
      ...characterRefInfos.map((c) => `@图片${c.index}是${c.name}`),
      ...sceneFrameInfos.map((s) => `@图片${s.index}是${s.label}`),
    ].join("，") + "。";

    const videoProvider = resolveVideoProvider(modelConfig, versionedUploadDir);

    const videoModelId = modelConfig?.video?.modelId;
    const videoMaxDuration = getModelMaxDuration(videoModelId);
    const effectiveDuration = Math.min(shot.duration ?? 10, videoMaxDuration);

    // Step 3: Use stored videoPrompt if available; otherwise auto-plan via AI
    let videoPrompt: string;
    if (shot.videoPrompt) {
      // If the stored prompt already has mapping, trust it; otherwise prepend.
      videoPrompt = shot.videoPrompt.includes("图像映射")
        ? shot.videoPrompt
        : `图像映射：${fullMapping}。\n\n${shot.videoPrompt}`;
    } else {
      const textProvider = resolveAIProvider(modelConfig);
      const refVideoSystem = await resolvePrompt("ref_video_prompt", { userId, projectId });
      try {
        const motionContext = shot.motionScript || shot.videoScript || shot.prompt || "";
        const promptRequest = buildRefVideoPromptRequest({
          motionScript: motionContext,
          cameraDirection: shot.cameraDirection || "static",
          duration: effectiveDuration,
          characters: characterRefInfos,
          sceneFrames: sceneFrameInfos,
          dialogues: undefined,
            // TODO: load per-shot dialogues for batch H3
        });
        console.log(`[SingleReferenceVideo] Shot ${shot.sequence} promptRequest:\n${promptRequest}`);
        const rawPrompt = await textProvider.generateText(promptRequest, {
          systemPrompt: refVideoSystem,
          images: sceneFramePaths,
          temperature: 0.7,
        });
        videoPrompt = `Duration: ${effectiveDuration}s.\n\n${rawPrompt.trim()}`;
      } catch (err) {
        console.warn("[SingleReferenceVideo] Vision prompt generation failed, falling back:", err);
        const fallback = buildReferenceVideoPrompt({
          videoScript: shot.videoScript || shot.motionScript || shot.prompt || "",
          cameraDirection: shot.cameraDirection || "static",
          duration: effectiveDuration,
          characters: projectCharacters,
          dialogues: undefined,
            // TODO: load per-shot dialogues for batch H3
          slotContents: refVideoSlots,
        });
        videoPrompt = `图像映射：${fullMapping}。\n\n${fallback}`;
      }
    }

    console.log(`[SingleReferenceVideo] Shot ${shot.sequence}: generating video with ${orderedRefImages.length} reference images`);

    const result = await videoProvider.generateVideo({
      initialImage: sceneFramePaths[0],
      prompt: videoPrompt,
      duration: effectiveDuration,
      ratio,
      referenceImages: orderedRefImages,
    });

    await insertAssetVersion({
      shotId, type: "reference_video", sequenceInType: 0,
      prompt: videoPrompt, fileUrl: result.filePath, status: "completed",
      meta: result.lastFrameUrl ? { lastFrameUrl: result.lastFrameUrl } : null,
    });
    await db
      .update(shots)
      .set({ status: "completed" })
      .where(eq(shots.id, shotId));

    return NextResponse.json({ shotId, referenceVideoUrl: result.filePath, status: "ok" });
  } catch (err) {
    console.error(`[SingleReferenceVideo] Error for shot ${shot.sequence}:`, err);
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shotId));
    return NextResponse.json(
      { shotId, status: "error", error: extractErrorMessage(err) },
      { status: 500 }
    );
  }
}

// --- batch_reference_video: sequential text2video for all eligible shots ---

async function handleBatchReferenceVideo(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  if (!modelConfig?.video) {
    return NextResponse.json({ error: "No video model configured" }, { status: 400 });
  }
  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const batchVersionId = payload?.versionId as string | undefined;
  const shotWhereConditions = [eq(shots.projectId, projectId)];
  if (batchVersionId) shotWhereConditions.push(eq(shots.versionId, batchVersionId));
  if (episodeId) shotWhereConditions.push(eq(shots.episodeId, episodeId));
  const allShots = await db
    .select()
    .from(shots)
    .where(and(...shotWhereConditions))
    .orderBy(asc(shots.sequence));

  const versionedUploadDir = batchVersionId
    ? await getVersionedUploadDir(batchVersionId)
    : getUploadDir();

  const overwrite = payload?.overwrite === true;
  const allShotsLegacy = await loadShotLegacyViewsBatch(allShots.map((s) => s.id));
  const eligible = allShots.filter((s) => {
    const v = allShotsLegacy.get(s.id);
    return s.status !== "generating" && (overwrite || !v?.referenceVideoUrl);
  });
  if (eligible.length === 0) {
    return NextResponse.json({ results: [], message: "No eligible shots" });
  }

  const projectCharacters = await getEpisodeCharacters(projectId, episodeId);

  // Character list is now per-shot (derived from that shot's reference
  // assets' `characters` metadata). Project-wide charRefs is not used in
  // the batch pipeline anymore; it's computed fresh inside the shot loop.
  const charsWithRefsAll = projectCharacters.filter((c) => !!c.referenceImage);
  if (charsWithRefsAll.length === 0) {
    return NextResponse.json(
      { error: "No character reference images available." },
      { status: 400 }
    );
  }

  const characterDescriptions = projectCharacters
    .map((c) => `${c.name}: ${c.description}`)
    .join("\n");

  const imageProvider = resolveImageProvider(modelConfig, versionedUploadDir);
  const videoProvider = resolveVideoProvider(modelConfig, versionedUploadDir);
  const textProvider = resolveAIProvider(modelConfig);
  const refVideoSystem = await resolvePrompt("ref_video_prompt", { userId, projectId });
  const ratio = (payload?.ratio as string) || "16:9";
  const videoMaxDuration = getModelMaxDuration(modelConfig?.video?.modelId);
  const refVideoSlots = await resolveSlotContents("ref_video_generate", { userId, projectId });

  await Promise.all(
    eligible.map((shot) =>
      db.update(shots).set({ status: "generating" }).where(eq(shots.id, shot.id))
    )
  );

  const results = await Promise.all(
    eligible.map(async (shot): Promise<{ shotId: string; sequence: number; status: "ok" | "error"; referenceVideoUrl?: string; error?: string }> => {
      try {
        const shotLegacy = allShotsLegacy.get(shot.id)!;
        const effectiveDuration = Math.min(shot.duration ?? 10, videoMaxDuration);
        const shotDialogues = await db
          .select({ text: dialogues.text, characterId: dialogues.characterId, sequence: dialogues.sequence })
          .from(dialogues)
          .where(eq(dialogues.shotId, shot.id))
          .orderBy(asc(dialogues.sequence));
        const videoContextForDialogue = shot.motionScript || shot.videoScript || shot.prompt || "";
        const onScreenDialogueChars = shotDialogues
          .map((d) => projectCharacters.find((c) => c.id === d.characterId)?.name ?? "Unknown")
          .filter((name) => isCharacterOnScreen(name, videoContextForDialogue, shotLegacy.startFrameDesc));

        const dialogueList = shotDialogues.map((d) => {
          const char = projectCharacters.find((c) => c.id === d.characterId);
          const characterName = char?.name ?? "Unknown";
          const onScreen = isCharacterOnScreen(characterName, videoContextForDialogue, shotLegacy.startFrameDesc);
          const visualHint = onScreen ? (char?.visualHint || undefined) : undefined;
          return {
            characterName,
            text: d.text,
            offscreen: !onScreen,
            visualHint,
          };
        });

        // Step 1: Collect all scene frames (pure environments, ordered by sequenceInType)
        const sceneFramePaths: string[] = shotLegacy.referenceImages
          .filter((r) => r.fileUrl)
          .sort((a, b) => a.sequenceInType - b.sequenceInType)
          .map((r) => r.fileUrl as string);

        if (sceneFramePaths.length === 0) {
          throw new Error("No scene reference images. Generate scene reference images first.");
        }

        // Per-shot character set from ref assets' metadata
        const shotCharNameSet = new Set<string>();
        for (const r of shotLegacy.referenceImages) {
          for (const n of r.characters ?? []) shotCharNameSet.add(stripCharHint(n));
        }
        const charRefs = charsWithRefsAll
          .filter((c) => shotCharNameSet.size === 0 || shotCharNameSet.has(stripCharHint(c.name)) || shotCharNameSet.has((c as any).baseName || ""))
          .map((c) => ({ name: c.name, imagePath: c.referenceImage as string }));

        // Step 2: Build ordered Seedance 2 reference image list (chars first, scenes second)
        const orderedRefImages: string[] = [
          ...charRefs.map((c) => c.imagePath),
          ...sceneFramePaths,
        ];
        const characterRefInfos = charRefs.map((c, i) => ({
          name: c.name,
          index: i + 1,
          visualHint: projectCharacters.find((pc) => pc.name === c.name)?.visualHint,
        }));
        // Scene labels: prefer AI-generated sceneName from meta, fall back to index
        const sceneAssetList = shotLegacy.referenceImages
          .filter((r) => r.fileUrl)
          .sort((a, b) => a.sequenceInType - b.sequenceInType);
        const sceneFrameInfos = sceneFramePaths.map((_, i) => {
          const metaObj = sceneAssetList[i]?.meta as { sceneName?: string } | null;
          const name = metaObj?.sceneName || (sceneFramePaths.length > 1 ? `场景-${i + 1}` : `场景`);
          return { label: name, index: charRefs.length + i + 1 };
        });
        const fullMapping = [
          ...characterRefInfos.map((c) => `@图片${c.index}是${c.name}`),
          ...sceneFrameInfos.map((s) => `@图片${s.index}是${s.label}`),
        ].join("，") + "。";

        // Step 3: Resolve video prompt
        let videoPrompt: string;
        if (shot.videoPrompt) {
          videoPrompt = shot.videoPrompt.includes("图像映射")
            ? shot.videoPrompt
            : `图像映射：${fullMapping}。\n\n${shot.videoPrompt}`;
        } else {
          try {
            const motionContext = shot.motionScript || shot.videoScript || shot.prompt || "";
            const promptRequest = buildRefVideoPromptRequest({
              motionScript: motionContext,
              cameraDirection: shot.cameraDirection || "static",
              duration: effectiveDuration,
              characters: characterRefInfos,
              sceneFrames: sceneFrameInfos,
              dialogues: undefined,
            // TODO: load per-shot dialogues for batch H3
            });
            const rawPrompt = await textProvider.generateText(promptRequest, {
              systemPrompt: refVideoSystem,
              images: sceneFramePaths,
              temperature: 0.7,
            });
            videoPrompt = `Duration: ${effectiveDuration}s.\n\n${rawPrompt.trim()}`;
          } catch (err) {
            console.warn("[BatchReferenceVideo] Vision prompt generation failed, falling back:", err);
            const fallback = buildReferenceVideoPrompt({
              videoScript: shot.videoScript || shot.motionScript || shot.prompt || "",
              cameraDirection: shot.cameraDirection || "static",
              duration: effectiveDuration,
              characters: projectCharacters,
              dialogues: undefined,
            // TODO: load per-shot dialogues for batch H3
              slotContents: refVideoSlots,
            });
            videoPrompt = `图像映射：${fullMapping}。\n\n${fallback}`;
          }
        }

        console.log(`[BatchReferenceVideo] Shot ${shot.sequence}: ${sceneFramePaths.length} scenes + ${charRefs.length} chars → video`);

        const result = await videoProvider.generateVideo({
          initialImage: sceneFramePaths[0],
          prompt: videoPrompt,
          duration: effectiveDuration,
          ratio,
          referenceImages: orderedRefImages,
        });

        await insertAssetVersion({
          shotId: shot.id, type: "reference_video", sequenceInType: 0,
          prompt: videoPrompt, fileUrl: result.filePath, status: "completed",
          meta: result.lastFrameUrl ? { lastFrameUrl: result.lastFrameUrl } : null,
        });
        await db
          .update(shots)
          .set({ status: "completed" })
          .where(eq(shots.id, shot.id));

        console.log(`[BatchReferenceVideo] Shot ${shot.sequence} completed`);
        return { shotId: shot.id, sequence: shot.sequence, status: "ok", referenceVideoUrl: result.filePath };
      } catch (err) {
        console.error(`[BatchReferenceVideo] Error for shot ${shot.sequence}:`, err);
        await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shot.id));
        return {
          shotId: shot.id,
          sequence: shot.sequence,
          status: "error",
          error: extractErrorMessage(err),
        };
      }
    })
  );

  return NextResponse.json({ results });
}

// --- video_assemble: synchronous ffmpeg concat + subtitle burn ---

async function handleVideoAssembleSync(projectId: string, payload?: Record<string, unknown>, episodeId?: string) {
  let generationModeValue: string = "keyframe";
  if (episodeId) {
    const [episode] = await db.select({ generationMode: episodes.generationMode }).from(episodes).where(eq(episodes.id, episodeId));
    generationModeValue = episode?.generationMode ?? "keyframe";
  } else {
    const [project] = await db.select({ generationMode: projects.generationMode }).from(projects).where(eq(projects.id, projectId));
    generationModeValue = project?.generationMode ?? "keyframe";
  }

  let versionId = payload?.versionId as string | undefined;

  // If no versionId provided, fall back to the latest version for this project/episode
  if (!versionId) {
    const versionWhere = episodeId
      ? and(eq(storyboardVersions.projectId, projectId), eq(storyboardVersions.episodeId, episodeId))
      : eq(storyboardVersions.projectId, projectId);
    const [latestVersion] = await db
      .select({ id: storyboardVersions.id })
      .from(storyboardVersions)
      .where(versionWhere)
      .orderBy(desc(storyboardVersions.versionNum))
      .limit(1);
    versionId = latestVersion?.id;
  }

  const shotWhereConditions = [eq(shots.projectId, projectId)];
  if (versionId) shotWhereConditions.push(eq(shots.versionId, versionId));
  if (episodeId) shotWhereConditions.push(eq(shots.episodeId, episodeId));
  const projectShots = await db
    .select()
    .from(shots)
    .where(and(...shotWhereConditions))
    .orderBy(asc(shots.sequence));

  const isReference = generationModeValue === "reference";
  const projectShotsLegacy = await loadShotLegacyViewsBatch(projectShots.map((s) => s.id));
  const videoPaths = projectShots
    .map((s) => {
      const v = projectShotsLegacy.get(s.id);
      return isReference ? v?.referenceVideoUrl : v?.videoUrl;
    })
    .filter(Boolean) as string[];

  if (videoPaths.length === 0) {
    return NextResponse.json({ error: "No video clips to assemble" }, { status: 400 });
  }

  // Build transitions array from shot transitionOut / transitionIn fields
  type TransitionType = "cut" | "dissolve" | "fade_in" | "fade_out" | "wipeleft" | "slideright" | "circleopen";
  const completedShots = projectShots.filter((s) => {
    const v = projectShotsLegacy.get(s.id);
    return isReference ? v?.referenceVideoUrl : v?.videoUrl;
  });
  const transitions: TransitionType[] = completedShots.slice(0, -1).map((shot, i) => {
    const nextShot = completedShots[i + 1];
    return ((shot.transitionOut && shot.transitionOut !== "cut")
      ? shot.transitionOut
      : (nextShot?.transitionIn || "cut")) as TransitionType;
  });

  // Get dialogues for subtitles
  const allSubtitles: {
    text: string;
    shotSequence: number;
    dialogueSequence: number;
    dialogueCount: number;
    startRatio?: number;
    endRatio?: number;
  }[] = [];
  for (const shot of completedShots) {
    const shotDialogues = await db
      .select({
        text: dialogues.text,
        characterName: characters.name,
        sequence: dialogues.sequence,
        shotSequence: shots.sequence,
        startRatio: dialogues.startRatio,
        endRatio: dialogues.endRatio,
      })
      .from(dialogues)
      .innerJoin(characters, eq(dialogues.characterId, characters.id))
      .innerJoin(shots, eq(dialogues.shotId, shots.id))
      .where(eq(dialogues.shotId, shot.id))
      .orderBy(asc(dialogues.sequence));

    const count = shotDialogues.length;
    shotDialogues.forEach((d, idx) => {
      const sr = d.startRatio ? parseFloat(String(d.startRatio)) : undefined;
      const er = d.endRatio ? parseFloat(String(d.endRatio)) : undefined;
      allSubtitles.push({
        text: `${d.characterName}: ${d.text}`,
        shotSequence: d.shotSequence,
        dialogueSequence: idx,
        dialogueCount: count,
        startRatio: sr,
        endRatio: er,
      });
    });
  }

  try {
    const result = await assembleVideo({
      videoPaths,
      subtitles: allSubtitles,
      projectId,
      shotDurations: completedShots.map((s) => s.duration ?? 10),
      transitions,
    });

    if (episodeId) {
      await db
        .update(episodes)
        .set({ status: "completed", finalVideoUrl: result.videoPath, updatedAt: new Date() })
        .where(eq(episodes.id, episodeId));
    } else {
      await db
        .update(projects)
        .set({ status: "completed", finalVideoUrl: result.videoPath, updatedAt: new Date() })
        .where(eq(projects.id, projectId));
    }

    console.log(`[VideoAssemble] Completed: ${result.videoPath}`);
    return NextResponse.json({ outputPath: result.videoPath, srtPath: result.srtPath, status: "ok" });
  } catch (err) {
    console.error("[VideoAssemble] Error:", err);
    return NextResponse.json({ status: "error", error: extractErrorMessage(err) }, { status: 500 });
  }
}

// ─── Generate Video Prompt (single) ──────────────────────────────────────────

async function handleSingleVideoPrompt(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const shotId = payload?.shotId as string;
  console.log(`[SingleVideoPrompt] called, shotId=${shotId}`);
  if (!shotId) return NextResponse.json({ error: "shotId required" }, { status: 400 });

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId)).limit(1);
  if (!shot) return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  const shotView = await loadShotLegacyView(shot.id);

  // Determine generation mode to decide which frames to pass
  let genMode = "keyframe";
  if (shot.episodeId) {
    const [ep] = await db.select({ generationMode: episodes.generationMode }).from(episodes).where(eq(episodes.id, shot.episodeId));
    genMode = ep?.generationMode ?? "keyframe";
  } else {
    const [proj] = await db.select({ generationMode: projects.generationMode }).from(projects).where(eq(projects.id, projectId));
    genMode = proj?.generationMode ?? "keyframe";
  }

  // Keyframe mode: pass first + last frames for transition description
  // Reference mode: pass ALL scene reference frames (ordered) so multi-
  // scene shots (ground → sky etc.) get the full spatial context.
  const visionFrames: string[] = [];
  let sceneMetaList: Array<{ sceneName?: string } | null> = [];
  if (genMode === "reference") {
    const sceneAssets = shotView.referenceImages
      .filter((r) => r.fileUrl)
      .sort((a, b) => a.sequenceInType - b.sequenceInType);
    for (const r of sceneAssets) {
      visionFrames.push(r.fileUrl as string);
      sceneMetaList.push((r.meta as { sceneName?: string } | null) ?? null);
    }
    if (visionFrames.length === 0 && shotView.sceneRefFrame) {
      visionFrames.push(shotView.sceneRefFrame);
      sceneMetaList.push(null);
    }
  } else {
    if (shotView.firstFrame) visionFrames.push(shotView.firstFrame);
    if (shotView.lastFrame) visionFrames.push(shotView.lastFrame);
    if (visionFrames.length === 0 && shotView.sceneRefFrame) visionFrames.push(shotView.sceneRefFrame);
  }
  console.log(`[SingleVideoPrompt] shot.sequence=${shot.sequence}, mode=${genMode}, frames=${visionFrames.length}`);
  // Allow text-only prompt when no frames available (non-vision models)

  const shotCharacters = await db.select().from(characters).where(eq(characters.projectId, shot.projectId));

  // ── H3 prompt: build from structured data ──
  const textProvider = resolveAIProvider(modelConfig);

  try {
    const { buildVideoPromptLLM: buildH3 } = await import("@/lib/ai/prompts/h3");
    const h3System = await resolvePrompt("video_h3_prompt", { userId, projectId }).catch(() => undefined);
    const h3Lang = (process.env.H3_LANGUAGE as "zh" | "en" | undefined) || "zh";
    let genMode: "keyframe" | "reference" = "keyframe";
    if (shot.episodeId) {
      const [ep] = await db.select({ gm: episodes.generationMode }).from(episodes).where(eq(episodes.id, shot.episodeId));
      genMode = (ep?.gm as "keyframe" | "reference") || "keyframe";
    } else {
      const [proj] = await db.select({ gm: projects.generationMode }).from(projects).where(eq(projects.id, projectId));
      genMode = (proj?.gm as "keyframe" | "reference") || "keyframe";
    }
    const h3Output = await buildH3({
      videoScript: shot.videoScript || shot.motionScript || shot.prompt || "",
      motionScript: shot.motionScript,
      duration: shot.duration ?? 10,
      cameraDirection: shot.cameraDirection || "static",
      generationMode: genMode,
      characters: shotCharacters.map(c => ({
        id: c.id, name: c.name, description: c.description,
        visualHint: c.visualHint, referenceImage: c.referenceImage,
        performanceStyle: c.performanceStyle, scope: c.scope,
        heightCm: c.heightCm, bodyType: c.bodyType,
      })),
      firstFrame: shotView.firstFrame ? { fileUrl: shotView.firstFrame, prompt: shotView.startFrameDesc } : undefined,
      lastFrame: shotView.lastFrame ? { fileUrl: shotView.lastFrame, prompt: shotView.endFrameDesc } : undefined,
      soundDesign: shot.soundDesign || undefined,
      musicCue: shot.musicCue || undefined,
      languageMode: h3Lang,
    }, textProvider, h3System);
    const h3Text = h3Output.sections.join("\n\n");
    await db.update(shots).set({ videoPrompt: h3Text }).where(eq(shots.id, shotId));
    console.log(`[SingleVideoPrompt] H3 ${h3Output.mode} prompt generated`);
    return NextResponse.json({ shotId, videoPrompt: h3Text, status: "ok", mode: "h3" });
  } catch (err: any) {
    console.error("[SingleVideoPrompt] H3 failed:", err?.message);
    return NextResponse.json({ error: `H3 prompt failed: ${err?.message}` }, { status: 500 });
  }
}

// ─── Generate Video Prompt (batch) ───────────────────────────────────────────

async function handleBatchVideoPrompt(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  // === 智能体路由 ===
  // Check generation mode to decide which agent category to use
  const vpModeSource = episodeId
    ? await db.select({ mode: episodes.generationMode }).from(episodes).where(eq(episodes.id, episodeId))
    : await db.select({ mode: projects.generationMode }).from(projects).where(eq(projects.id, projectId));
  const vpCategory: AgentCategory = vpModeSource[0]?.mode === "reference" ? "ref_video_prompts" : "video_prompts";
  const vpBoundAgent = await findBoundAgent(projectId, vpCategory);
  if (vpBoundAgent) {
    // Build prompt from shots data (same info as built-in pipeline)
    const vpVersionId = payload?.versionId as string | undefined;
    const vpWhereConds = [eq(shots.projectId, projectId)];
    if (vpVersionId) vpWhereConds.push(eq(shots.versionId, vpVersionId));
    if (episodeId) vpWhereConds.push(eq(shots.episodeId, episodeId));
    const vpAgentShots = await db.select().from(shots).where(and(...vpWhereConds)).orderBy(asc(shots.sequence));
    if (vpAgentShots.length === 0) {
      return NextResponse.json({ error: "没有分镜数据，请先生成分镜" }, { status: 400 });
    }
    const vpAgentChars = await getEpisodeCharacters(projectId, episodeId);
    const vpPrompt = JSON.stringify({
      shots: vpAgentShots.map((s) => ({
        sequence: s.sequence,
        sceneDescription: s.prompt,
        motionScript: s.motionScript,
        videoScript: s.videoScript,
        cameraDirection: s.cameraDirection,
        duration: s.duration,
      })),
      characters: vpAgentChars.map((c) => ({ name: c.name, visualHint: c.visualHint })),
    }, null, 2);

    const agentResult = await callAndValidateAgent(vpBoundAgent, "video_prompts", vpPrompt);
    if (agentResult instanceof NextResponse) return agentResult;

    // Parse agent output and save videoPrompt to each shot
    try {
      const vpParsed = parseLLMJSON(agentResult.text) as Array<Record<string, unknown>>;

      let updatedCount = 0;
      for (const entry of vpParsed) {
        const seq = (entry.sequence as number) ?? (entry.shotSequence as number);
        const shot = vpAgentShots.find((s) => s.sequence === seq);
        if (!shot) continue;
        const videoPrompt = (entry.videoPrompt || entry.prompt || "") as string;
        if (videoPrompt) {
          await db.update(shots).set({ videoPrompt: `Duration: ${shot.duration || 8}s.\n\n${videoPrompt.trim()}` }).where(eq(shots.id, shot.id));
          updatedCount++;
        }
      }
      console.log(`[VideoPrompts Agent] Updated ${updatedCount} shots`);
      return NextResponse.json({ results: vpParsed.map((e) => ({ shotId: e.sequence, status: "ok" })), status: "ok" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return NextResponse.json({ error: `智能体视频提示词解析失败: ${msg}` }, { status: 422 });
    }
  }
  // === 智能体路由结束 ===

  let batchVersionId = payload?.versionId as string | undefined;
  if (!batchVersionId) {
    const [latestVer] = await db.select({ id: storyboardVersions.id })
      .from(storyboardVersions)
      .where(and(
        eq(storyboardVersions.projectId, projectId),
        ...(episodeId ? [eq(storyboardVersions.episodeId, episodeId)] : [])
      ))
      .orderBy(desc(storyboardVersions.versionNum))
      .limit(1);
    if (!latestVer?.id) return NextResponse.json({ error: "No version found. Run shot split first." }, { status: 400 });
    batchVersionId = latestVer.id;
  }

  const shotWhereConditions = [eq(shots.projectId, projectId)];
  if (batchVersionId) shotWhereConditions.push(eq(shots.versionId, batchVersionId));
  if (episodeId) shotWhereConditions.push(eq(shots.episodeId, episodeId));
  const batchShots = await db.select().from(shots).where(and(...shotWhereConditions)).orderBy(asc(shots.sequence));
  const batchShotsLegacy = await loadShotLegacyViewsBatch(batchShots.map((s) => s.id));

  const batchCharacters = await getEpisodeCharacters(projectId, episodeId);

  // Only process shots that have frames and no completed video yet
  const eligible = batchShots.filter((s) => {
    const v = batchShotsLegacy.get(s.id);
    return v?.firstFrame || v?.lastFrame || v?.sceneRefFrame;
  });

  // Skip shots that already have a completed keyframe_video —
  // user must use single_video_prompt to explicitly regenerate.
  const { shotAssets: saForGuard } = await import("@/lib/db/schema");
  const completedVideoShotIds = new Set((await db
    .select({ shotId: saForGuard.shotId })
    .from(saForGuard)
    .where(and(
      eq(saForGuard.type, "keyframe_video"),
      eq(saForGuard.status, "completed"),
      eq(saForGuard.isActive, 1)
    )))
    .map(r => r.shotId));
  const skipped = eligible.filter(s => completedVideoShotIds.has(s.id));
  if (skipped.length > 0) {
    console.log(`[BatchH3VideoPrompt] Skipping ${skipped.length} shot(s) with completed video (seq: ${skipped.map(s => s.sequence).join(", ")})`);
  }
  const eligibleFinal = eligible.filter(s => !completedVideoShotIds.has(s.id));
  if (eligibleFinal.length === 0) {
    return NextResponse.json({
      results: eligible.map(s => ({ shotId: s.id, sequence: s.sequence, status: "skipped", reason: "video_exists" })),
      status: "ok", mode: "h3",
    });
  }

  // ── H3 prompt: build from structured data (shared system prompt) ──
  const textProvider = resolveAIProvider(modelConfig);
  const h3System = await resolvePrompt("video_h3_prompt", { userId, projectId }).catch(() => undefined);
  const h3Lang = (process.env.H3_LANGUAGE as "zh" | "en" | undefined) || "zh";
  const results = await Promise.all(
    eligibleFinal.map(async (shot) => {
      try {
        const { buildVideoPromptLLM: buildH3 } = await import("@/lib/ai/prompts/h3");
        const shotLegacy = batchShotsLegacy.get(shot.id);
        const effectiveDuration = shot.duration ?? 10;
        // Determine generation mode
        let genMode: "keyframe" | "reference" = "keyframe";
        if (episodeId) {
          const [ep] = await db.select({ gm: episodes.generationMode }).from(episodes).where(eq(episodes.id, episodeId));
          genMode = (ep?.gm as "keyframe" | "reference") || "keyframe";
        } else {
          const [proj] = await db.select({ gm: projects.generationMode }).from(projects).where(eq(projects.id, projectId));
          genMode = (proj?.gm as "keyframe" | "reference") || "keyframe";
        }
        const h3Output = await buildH3({
          videoScript: shot.videoScript || shot.motionScript || shot.prompt || "",
          motionScript: shot.motionScript,
          duration: effectiveDuration,
          cameraDirection: shot.cameraDirection || "static",
          generationMode: genMode,
          characters: batchCharacters.map(c => ({
            id: c.id, name: c.name, description: c.description,
            visualHint: c.visualHint, referenceImage: c.referenceImage,
            performanceStyle: c.performanceStyle, scope: c.scope,
            heightCm: c.heightCm, bodyType: c.bodyType,
          })),
          firstFrame: shotLegacy?.firstFrame ? { fileUrl: shotLegacy.firstFrame, prompt: shotLegacy.startFrameDesc } : undefined,
          lastFrame: shotLegacy?.lastFrame ? { fileUrl: shotLegacy.lastFrame, prompt: shotLegacy.endFrameDesc } : undefined,
          soundDesign: shot.soundDesign || undefined,
          musicCue: shot.musicCue || undefined,
          languageMode: h3Lang,
          dialogues: undefined,
          // TODO: load per-shot dialogues for batch H3
        }, textProvider, h3System);
        const h3Text = h3Output.sections.join("\n\n");
        await db.update(shots).set({ videoPrompt: h3Text }).where(eq(shots.id, shot.id));
        console.log(`[BatchH3VideoPrompt] Shot ${shot.sequence} ok (${h3Output.mode})`);
        return { shotId: shot.id, status: "ok" };
      } catch (err: any) {
        console.error(`[BatchH3VideoPrompt] Shot ${shot.sequence} failed:`, err?.message);
        return { shotId: shot.id, status: "error" };
      }
    })
  );
  const ok = results.filter(r => r.status === "ok").length;
  console.log(`[BatchH3VideoPrompt] Done: ${ok}/${eligibleFinal.length} ok${skipped.length > 0 ? ` (${skipped.length} skipped)` : ""}`);
  const skippedResults = skipped.map(s => ({ shotId: s.id, sequence: s.sequence, status: "skipped", reason: "video_exists" }));
  return NextResponse.json({ results: [...results, ...skippedResults], ok, skipped: skipped.length, status: "ok", mode: "h3" });
}

// --- ai_optimize_text: use AI to optimize a text field ---

async function handleAiOptimizeText(
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const originalText = payload?.originalText as string;
  const instruction = payload?.instruction as string;
  const images = (payload?.images as string[] | undefined) || [];

  if (!originalText || !instruction) {
    return NextResponse.json({ error: "Missing originalText or instruction" }, { status: 400 });
  }
  if (!modelConfig?.text) {
    return NextResponse.json({ error: "No text model configured" }, { status: 400 });
  }

  const systemPrompt = images.length > 0
    ? `你是一位专业的AI动画内容优化专家。用户会给你一段原始文本、当前生成的图片以及优化指令。请仔细观察图片中的不合理之处（如比例失调、角色错位、风格不一致、细节缺失等），结合优化指令重写原始文本。
规则：
- 只输出优化后的文本，不要添加任何解释、前言或标记
- 保持原文的语言（中文输入→中文输出）
- 保持原文的整体结构和用途
- 必须分析图片中存在的问题，并在优化后的文本中明确修复这些问题
- 例如：如果图片中儿童被画得跟成人一样大，优化文本要强调"儿童身高约110cm，明显矮于成人"
- 例如：如果角色服装与原文不符，优化文本要更明确地描述服装细节`
    : `你是一位专业的AI动画内容优化专家。用户会给你一段原始文本和优化指令，请根据指令优化原始文本。
规则：
- 只输出优化后的文本，不要添加任何解释、前言或标记
- 保持原文的语言（中文输入→中文输出）
- 保持原文的整体结构和用途
- 根据优化指令做针对性改进`;

  // Use vision-capable text provider when images present
  if (images.length > 0) {
    const ai = resolveAIProvider(modelConfig);
    const result = await ai.generateText(
      `原始文本：\n${originalText}\n\n优化指令：\n${instruction}\n\n请观察上方图片中的问题，结合指令输出优化后的文本：`,
      {
        systemPrompt,
        images,
        temperature: 0.7,
      }
    );
    return NextResponse.json({ optimizedText: result.trim() });
  }

  const model = createLanguageModel(modelConfig.text);
  const { text } = await generateText({
    model,
    system: systemPrompt,
    prompt: `原始文本：
${originalText}

优化指令：
${instruction}

请输出优化后的文本：`,
  });

  return NextResponse.json({ optimizedText: text.trim() });
}

// --- batch_ref_image_generate: generate all pending reference images across shots ---

async function handleBatchRefImageGenerate(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const batchVersionId = payload?.versionId as string | undefined;
  const shotWhereConditions = [eq(shots.projectId, projectId)];
  if (batchVersionId) shotWhereConditions.push(eq(shots.versionId, batchVersionId));
  if (episodeId) shotWhereConditions.push(eq(shots.episodeId, episodeId));

  const allShots = await db
    .select()
    .from(shots)
    .where(and(...shotWhereConditions))
    .orderBy(asc(shots.sequence));

  const versionedUploadDir = batchVersionId
    ? await getVersionedUploadDir(batchVersionId)
    : getUploadDir();

  const imageProvider = resolveImageProvider(modelConfig, versionedUploadDir);

  const results: Array<{
    shotId: string;
    sequence: number;
    generated: number;
    failed: number;
  }> = [];

  const allShotsLegacy = await loadShotLegacyViewsBatch(allShots.map((s) => s.id));
  for (const shot of allShots) {
    const refImages = allShotsLegacy.get(shot.id)?.referenceImages ?? [];
    const pending = refImages.filter((r) => r.status === "pending" && r.prompt.trim());

    if (pending.length === 0) {
      results.push({ shotId: shot.id, sequence: shot.sequence, generated: 0, failed: 0 });
      continue;
    }

    let generated = 0;
    let failed = 0;

    for (const entry of pending) {
      try {
        const batchRatio = (payload?.ratio as string) || "16:9";
        const batchImageOpts = { size: ratioToSize(batchRatio), aspectRatio: batchRatio };

        // Scene-only: do NOT inject character references. Scene frames are
        // pure environments; character consistency is handled at the video
        // generation step via Seedance 2 multi-reference mode.
        const imagePath = await imageProvider.generateImage(entry.prompt, {
          quality: "hd",
          ...batchImageOpts,
        });
        await insertAssetVersion({
          shotId: shot.id, type: "reference", sequenceInType: entry.sequenceInType,
          prompt: entry.prompt, fileUrl: imagePath, status: "completed",
          characters: entry.characters ?? undefined,
        });
        generated++;
        console.log(`[BatchRefImage] Shot ${shot.sequence}: generated ref image "${entry.id}"`);
      } catch (err) {
        failed++;
        console.warn(`[BatchRefImage] Shot ${shot.sequence}: failed ref image "${entry.id}":`, err);
      }
    }

    results.push({ shotId: shot.id, sequence: shot.sequence, generated, failed });
  }

  return NextResponse.json({ results });
}

// --- single_ref_image_generate: generate or regenerate a single reference image ---

async function handleSingleRefImageGenerate(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const shotId = payload?.shotId as string;
  const refImageId = payload?.refImageId as string;

  if (!shotId || !refImageId) {
    return NextResponse.json({ error: "Missing shotId or refImageId" }, { status: 400 });
  }
  if (!modelConfig?.image) {
    return NextResponse.json({ error: "No image model configured" }, { status: 400 });
  }

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) {
    return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  }

  const shotView = await loadShotLegacyView(shot.id);
  const refImages = shotView.referenceImages;
  const entry = refImages.find((r) => r.id === refImageId);
  if (!entry) {
    return NextResponse.json({ error: "Reference image not found" }, { status: 404 });
  }
  if (!entry.prompt.trim()) {
    return NextResponse.json({ error: "No prompt provided" }, { status: 400 });
  }

  console.log(`[SingleRefImage] Shot ${shot.sequence}: generating scene-only ref image "${refImageId}"`);

  const ratio = (payload?.ratio as string) || "16:9";
  const imgOpts = { size: ratioToSize(ratio), aspectRatio: ratio };
  const imageProvider = resolveImageProvider(modelConfig);

  try {
    // Scene-only: do NOT inject character references here.
    const imagePath = await imageProvider.generateImage(entry.prompt, {
      quality: "hd",
      ...imgOpts,
    });

    await insertAssetVersion({
      shotId, type: "reference", sequenceInType: entry.sequenceInType,
      prompt: entry.prompt, fileUrl: imagePath, status: "completed",
      characters: entry.characters ?? undefined,
    });

    return NextResponse.json({ ok: true, imagePath });
  } catch (err) {
    return NextResponse.json({ error: `Generation failed: ${err}` }, { status: 500 });
  }
}

// --- generate_ref_prompts: AI generates 1-4 reference image prompts per shot ---

async function handleGenerateRefPrompts(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  // === 智能体路由 ===
  const refBoundAgent = await findBoundAgent(projectId, "ref_image_prompts");
  if (refBoundAgent) {
    const refVersionId = payload?.versionId as string | undefined;
    const refWhereConds = [eq(shots.projectId, projectId)];
    if (refVersionId) refWhereConds.push(eq(shots.versionId, refVersionId));
    if (episodeId) refWhereConds.push(eq(shots.episodeId, episodeId));
    const refAgentShots = await db.select().from(shots).where(and(...refWhereConds)).orderBy(asc(shots.sequence));
    if (refAgentShots.length === 0) {
      return NextResponse.json({ error: "没有分镜数据，请先生成分镜" }, { status: 400 });
    }
    const refAgentChars = await getEpisodeCharacters(projectId, episodeId);
    const refPrompt = JSON.stringify({
      shots: refAgentShots.map((s) => ({
        sequence: s.sequence,
        sceneDescription: s.prompt,
        motionScript: s.motionScript,
        cameraDirection: s.cameraDirection,
        duration: s.duration,
      })),
      characters: refAgentChars.map((c) => ({ name: c.name, description: c.description, visualHint: c.visualHint })),
    }, null, 2);

    const agentResult = await callAndValidateAgent(refBoundAgent, "ref_image_prompts", refPrompt);
    if (agentResult instanceof NextResponse) return agentResult;

    try {
      const refParsed = parseLLMJSON(agentResult.text) as Array<Record<string, unknown>>;
      if (!Array.isArray(refParsed)) {
        return NextResponse.json({ error: "智能体必须返回 JSON 数组格式的参考图提示词" }, { status: 422 });
      }

      let savedCount = 0;
      console.log(`[RefImagePrompts Agent] Parsed ${refParsed.length} entries, keys: ${refParsed[0] ? Object.keys(refParsed[0]).join(",") : "empty"}`);
      for (const entry of refParsed) {
        const seq = (entry.sequence as number) ?? (entry.shotSequence as number) ?? 0;
        const shot = refAgentShots.find((s) => s.sequence === seq);
        if (!shot) { console.log(`[RefImagePrompts Agent] No shot found for seq=${seq}`); continue; }

        const scenes = (entry.scenes || entry.prompts || []) as Array<Record<string, unknown>>;
        const chars = Array.isArray(entry.characters) ? entry.characters as string[] : [];
        console.log(`[RefImagePrompts Agent] seq=${seq}, scenes=${scenes.length}, chars=${chars.length}`);

        for (let i = 0; i < scenes.length; i++) {
          const scene = scenes[i];
          const prompt = (scene.prompt || scene as unknown as string || "") as string;
          const name = (scene.name || `scene_${i}`) as string;
          if (prompt && typeof prompt === "string") {
            await insertAssetVersion({
              shotId: shot.id,
              type: "reference",
              sequenceInType: i,
              prompt,
              status: "pending",
              characters: chars,
              meta: { sceneName: name },
            });
            savedCount++;
          }
        }
      }
      console.log(`[RefImagePrompts Agent] Saved ${savedCount} reference prompts`);
      return NextResponse.json({ updatedCount: refParsed.length, totalShots: refAgentShots.length });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return NextResponse.json({ error: `智能体参考图提示词解析失败: ${msg}` }, { status: 422 });
    }
  }
  // === 智能体路由结束 ===

  if (!modelConfig?.text) {
    return NextResponse.json({ error: "No text model configured" }, { status: 400 });
  }

  let batchVersionId = payload?.versionId as string | undefined;
  if (!batchVersionId) {
    const [latestVer] = await db.select({ id: storyboardVersions.id })
      .from(storyboardVersions)
      .where(and(
        eq(storyboardVersions.projectId, projectId),
        ...(episodeId ? [eq(storyboardVersions.episodeId, episodeId)] : [])
      ))
      .orderBy(desc(storyboardVersions.versionNum))
      .limit(1);
    if (!latestVer?.id) return NextResponse.json({ error: "No version found. Run shot split first." }, { status: 400 });
    batchVersionId = latestVer.id;
  }
  const buildWhere = (includeVersion: boolean) => {
    const conds = [eq(shots.projectId, projectId)];
    if (includeVersion && batchVersionId) conds.push(eq(shots.versionId, batchVersionId));
    if (episodeId) conds.push(eq(shots.episodeId, episodeId));
    return and(...conds);
  };

  let allShots = await db
    .select()
    .from(shots)
    .where(buildWhere(true))
    .orderBy(asc(shots.sequence));

  // Fallback: if the strict version filter returns empty (e.g. stale
  // selectedVersionId on the client), retry without version — use the
  // shots that actually exist for this project+episode.
  if (allShots.length === 0 && batchVersionId) {
    console.warn(`[GenerateRefPrompts] strict filter empty (versionId=${batchVersionId}), falling back to no-version filter`);
    allShots = await db
      .select()
      .from(shots)
      .where(buildWhere(false))
      .orderBy(asc(shots.sequence));
  }

  if (allShots.length === 0) {
    return NextResponse.json({ error: "No shots found" }, { status: 400 });
  }

  const projectCharacters = await getEpisodeCharacters(projectId, episodeId);

  // Get visual style from script — parse the fixed machine-readable meta block
  // (see src/lib/ai/prompts/script-generate.ts VISUAL STYLE section)
  const scriptSource = episodeId
    ? await db.select({ script: episodes.script }).from(episodes).where(eq(episodes.id, episodeId))
    : await db.select({ script: projects.script }).from(projects).where(eq(projects.id, projectId));
  const script = scriptSource[0]?.script || "";

  const pickField = (label: string): string => {
    const re = new RegExp(`${label}[：:]\\s*(.+?)(?:\\n|$)`);
    const m = script.match(re);
    return m?.[1]?.trim() || "";
  };
  const metaVisualStyle = pickField("视觉风格") || pickField("Visual Style");
  const metaColorTone = pickField("色彩基调");
  const metaEra = pickField("时代美学");
  const metaMood = pickField("氛围情绪");
  const metaRatio = pickField("画幅比例");
  // 参考导演 is intentionally NOT injected into visualStyle anymore —
  // it carries real person names that trigger content filters at both
  // the text LLM (400) and the image API (400 invalid_request_error).

  const visualStyle = [
    metaVisualStyle,
    metaColorTone && `色彩基调：${metaColorTone}`,
    metaEra && `时代美学：${metaEra}`,
    metaMood && `氛围情绪：${metaMood}`,
    metaRatio && `画幅比例：${metaRatio}`,
  ].filter(Boolean).join("；");

  // Load character relationships — drives on-screen interaction framing
  // when scene frames plan out the space for enemies / allies.
  const refRelations = await db
    .select()
    .from(characterRelations)
    .where(eq(characterRelations.projectId, projectId));
  let refRelationsText = "";
  if (refRelations.length > 0) {
    refRelationsText = "\n\n## 角色关系（必须用于决定场景空间规划）\n";
    for (const rel of refRelations) {
      const charA = projectCharacters.find((c) => c.id === rel.characterAId);
      const charB = projectCharacters.find((c) => c.id === rel.characterBId);
      if (charA && charB) {
        refRelationsText += `- ${charA.name} ↔ ${charB.name}：${rel.relationType}${rel.description ? `（${rel.description}）` : ""}\n`;
      }
    }
    refRelationsText += `
**关系驱动场景规划规则**：
- **敌对**：场景需要有明确的对峙空间轴线——两个站位点之间留出视觉通道。
- **友好/父女/师徒**：场景留出并肩站位的空间。
- 这些只影响场景帧的空间布局（景别/构图/空间轴线），场景帧本身**仍然不画任何人物**。
`;
  }

  const textProvider = resolveAIProvider(modelConfig);
  const refImageSystem = await resolvePrompt("ref_image_prompts", { userId, projectId });
  const { deleteAssetsByType } = await import("@/lib/shot-asset-utils");

  // Batch generation strategy — each LLM call receives a chunk of 8
  // consecutive shots so the AI can maintain narrative continuity across
  // them (lighting evolution, spatial flow, prop reuse). Batches run
  // SEQUENTIALLY so each batch can see the previous batch's last shot as
  // continuity context. Concurrent per-shot calls broke story coherence —
  // each shot got a near-duplicate "intro scene" from the LLM.
  const total = allShots.length;
  const BATCH_SIZE = 8;
  const batches: typeof allShots[] = [];
  for (let i = 0; i < allShots.length; i += BATCH_SIZE) {
    batches.push(allShots.slice(i, i + BATCH_SIZE));
  }
  console.log(`[GenerateRefPrompts] Starting sequential batched generation: ${batches.length} batch(es) of up to ${BATCH_SIZE} shots, total ${total}`);

  let updatedCount = 0;
  const failed: Array<{ seq: number; err: string }> = [];
  let previousBatchTail: { sequence: number; sceneName?: string; prompt: string } | null = null;

  for (let bi = 0; bi < batches.length; bi++) {
    const batch = batches[bi];
    const batchStart = Date.now();
    try {
      const baseRefRequest = buildRefImagePromptsRequest(
        batch.map((s) => ({
          sequence: s.sequence,
          prompt: s.prompt || "",
          motionScript: s.motionScript,
          cameraDirection: s.cameraDirection,
          duration: s.duration,
        })),
        projectCharacters.map((c) => ({ name: c.name, description: c.description })),
        visualStyle
      );

      let promptRequest = refRelationsText
        ? baseRefRequest + refRelationsText
        : baseRefRequest;

      // Continuity context from the last shot of the previous batch.
      if (previousBatchTail) {
        promptRequest += `\n\n## 剧情连续性上下文\n本批次的镜头 ${batch[0].sequence} 紧接上一批次镜头 ${previousBatchTail.sequence} 之后。上一个镜头的结束场景是"${previousBatchTail.sceneName || "未命名"}"：${previousBatchTail.prompt.slice(0, 160)}...\n请让本批次第一个镜头的场景在空间/光线/色调上与之自然衔接，避免突兀重置到"起始场景"风格。`;
      }

      const result = await textProvider.generateText(promptRequest, {
        systemPrompt: refImageSystem,
        temperature: 0.7,
      });

      const jsonMatch = result.match(/\[[\s\S]*\]/);
      if (!jsonMatch) {
        throw new Error(`Batch ${bi + 1}: invalid JSON response`);
      }
      const parsed = JSON.parse(jsonMatch[0]) as Array<{
        shotSequence: number;
        characters?: string[];
        scenes?: Array<{ name: string; prompt: string }>;
        prompts?: string[]; // legacy shape
      }>;

      let batchUpdated = 0;
      let lastEntryForContinuity: { sequence: number; sceneName?: string; prompt: string } | null = null;
      for (const shot of batch) {
        try {
          const entry = parsed.find((e) => e.shotSequence === shot.sequence);
          if (!entry) {
            console.warn(`[GenerateRefPrompts] batch ${bi + 1}: shot ${shot.sequence} missing from LLM output`);
            failed.push({ seq: shot.sequence, err: "missing from batch output" });
            continue;
          }

          // Normalize: accept new { scenes: [{name, prompt}] } or legacy
          // { prompts: [string] } format.
          let sceneList: Array<{ name: string; prompt: string }> = [];
          if (Array.isArray(entry.scenes) && entry.scenes.length > 0) {
            sceneList = entry.scenes.filter((s) => s && typeof s.prompt === "string" && s.prompt.trim());
          } else if (Array.isArray(entry.prompts) && entry.prompts.length > 0) {
            sceneList = entry.prompts.map((p, i) => ({ name: `场景 ${i + 1}`, prompt: p }));
          }
          if (sceneList.length === 0) {
            failed.push({ seq: shot.sequence, err: "empty scenes/prompts" });
            continue;
          }

          const shotCharacters = Array.isArray(entry.characters) ? entry.characters : [];
          if (shotCharacters.length === 0) {
            console.warn(`[GenerateRefPrompts] Shot ${shot.sequence}: AI did not emit 'characters' field`);
          }
          await deleteAssetsByType(shot.id, "reference");
          for (let pi = 0; pi < sceneList.length; pi++) {
            const scene = sceneList[pi];
            await insertAssetVersion({
              shotId: shot.id,
              type: "reference",
              sequenceInType: pi,
              prompt: scene.prompt,
              status: "pending",
              characters: shotCharacters,
              meta: { sceneName: scene.name || `场景 ${pi + 1}` },
            });
          }
          updatedCount++;
          batchUpdated++;
          // Track the last successfully parsed shot in this batch — fed
          // into the next batch as continuity context.
          const lastScene = sceneList[sceneList.length - 1];
          lastEntryForContinuity = {
            sequence: shot.sequence,
            sceneName: lastScene.name,
            prompt: lastScene.prompt,
          };
        } catch (shotErr) {
          failed.push({ seq: shot.sequence, err: String(shotErr) });
        }
      }
      if (lastEntryForContinuity) previousBatchTail = lastEntryForContinuity;
      const elapsed = ((Date.now() - batchStart) / 1000).toFixed(1);
      console.log(`[GenerateRefPrompts] ✓ batch ${bi + 1}/${batches.length} (${batch[0].sequence}..${batch[batch.length - 1].sequence}): ${batchUpdated}/${batch.length} shots in ${elapsed}s`);
    } catch (err) {
      const elapsed = ((Date.now() - batchStart) / 1000).toFixed(1);
      console.warn(`[GenerateRefPrompts] ✗ batch ${bi + 1}/${batches.length} failed in ${elapsed}s: ${String(err)}`);
      for (const shot of batch) failed.push({ seq: shot.sequence, err: String(err) });
    }
  }

  if (failed.length > 0) {
    console.warn(`[GenerateRefPrompts] ${failed.length} shots failed:`, failed);
  }
  console.log(`[GenerateRefPrompts] Updated ${updatedCount}/${total} shots (sequential batched)`);
  return NextResponse.json({ updatedCount, totalShots: total });
}

// --- single_ref_image_generate_all: generate all pending ref images for one shot ---

async function handleSingleShotRefImageGenerateAll(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig
) {
  const shotId = payload?.shotId as string;
  if (!shotId) return NextResponse.json({ error: "No shotId" }, { status: 400 });
  if (!modelConfig?.image) return NextResponse.json({ error: "No image model" }, { status: 400 });

  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) return NextResponse.json({ error: "Shot not found" }, { status: 404 });
  const shotView = await loadShotLegacyView(shot.id);

  const refImages = shotView.referenceImages;
  const pending = refImages.filter((r) => r.status === "pending" && r.prompt.trim());
  if (pending.length === 0) {
    return NextResponse.json({ message: "No pending ref images", generated: 0 });
  }

  // Scope characters to the shot's episode (or fall back to project-wide if shot has no episode)
  const projectCharacters = await getEpisodeCharacters(projectId, shot.episodeId);
  const charsWithRefs = projectCharacters.filter((c) => !!c.referenceImage);

  // Use pre-stored character names from ref prompt generation (no AI matching needed)
  const storedCharNames = pending[0]?.characters || [];
  const relevantChars = storedCharNames.length > 0
    ? charsWithRefs.filter((c) => storedCharNames.includes(c.name))
    : charsWithRefs.slice(0, 3); // fallback for legacy data without characters field
  const charRefsForShot = relevantChars.map((c) => c.referenceImage as string);

  // Build character mapping prompt prefix
  const promptPrefix = buildCharMappingPrefix(relevantChars);

  console.log(`[RefImageGenAll] Shot ${shot.sequence}: using ${relevantChars.length} chars: ${relevantChars.map(c => c.name).join(", ")}`);

  const ratio = (payload?.ratio as string) || "16:9";
  const imgOpts = { size: ratioToSize(ratio), aspectRatio: ratio };
  const imageProvider = resolveImageProvider(modelConfig);

  let generated = 0;
  for (const entry of pending) {
    try {
      const fullPrompt = promptPrefix + entry.prompt;
      const imagePath = await imageProvider.generateImage(fullPrompt, {
        quality: "hd",
        ...imgOpts,
        referenceImages: charRefsForShot,
      });
      await insertAssetVersion({
        shotId, type: "reference", sequenceInType: entry.sequenceInType,
        prompt: entry.prompt, fileUrl: imagePath, status: "completed",
        characters: entry.characters ?? undefined,
      });
      generated++;
      console.log(`[RefImageGenAll] Shot ${shot.sequence}: generated ref "${entry.id}"`);
    } catch (err) {
      console.warn(`[RefImageGenAll] Shot ${shot.sequence} ref ${entry.id} failed:`, err);
    }
  }

  return NextResponse.json({ generated, total: pending.length });
}

// --- generate_keyframe_prompts: synchronous batch — AI generates first/last
// frame prompts for all shots in one call, writes them into shot_assets ---

async function handleGenerateKeyframePrompts(
  projectId: string,
  userId: string,
  payload?: Record<string, unknown>,
  modelConfig?: ModelConfig,
  episodeId?: string
) {
  // === 智能体路由 ===
  const kpBoundAgent = await findBoundAgent(projectId, "keyframe_prompts");
  if (kpBoundAgent) {
    // Build prompt from shots data (same info as built-in pipeline)
    const batchVersionId = payload?.versionId as string | undefined;
    const kpWhereConds = [eq(shots.projectId, projectId)];
    if (batchVersionId) kpWhereConds.push(eq(shots.versionId, batchVersionId));
    if (episodeId) kpWhereConds.push(eq(shots.episodeId, episodeId));
    const kpAgentShots = await db.select().from(shots).where(and(...kpWhereConds)).orderBy(asc(shots.sequence));
    if (kpAgentShots.length === 0) {
      return NextResponse.json({ error: "没有分镜数据，请先生成分镜" }, { status: 400 });
    }
    const kpAgentChars = await getEpisodeCharacters(projectId, episodeId);
    const kpPrompt = JSON.stringify({
      shots: kpAgentShots.map((s) => ({
        sequence: s.sequence,
        sceneDescription: s.prompt,
        motionScript: s.motionScript,
        cameraDirection: s.cameraDirection,
        duration: s.duration,
      })),
      characters: kpAgentChars.map((c) => ({ name: c.name, description: c.description, visualHint: c.visualHint })),
    }, null, 2);

    const agentResult = await callAndValidateAgent(kpBoundAgent, "keyframe_prompts", kpPrompt);
    if (agentResult instanceof NextResponse) return agentResult;

    // Parse agent output — must be JSON array
    try {
      const kpParsed = parseLLMJSON(agentResult.text) as Array<Record<string, unknown>>;
      if (!Array.isArray(kpParsed)) {
        return NextResponse.json({ error: "智能体必须返回 JSON 数组格式的首尾帧提示词" }, { status: 422 });
      }

      let savedCount = 0;
      for (const entry of kpParsed) {
        const seq = (entry.sequence as number) ?? (entry.shotSequence as number) ?? 0;
        const shot = kpAgentShots.find((s) => s.sequence === seq);
        if (!shot) continue;

        const startFrame = (entry.startFrame || (entry.prompts as string[])?.[0] || "") as string;
        const endFrame = (entry.endFrame || (entry.prompts as string[])?.[1] || "") as string;
        const chars = Array.isArray(entry.characters) ? entry.characters as string[] : [];

        if (startFrame) {
          await insertAssetVersion({ shotId: shot.id, type: "first_frame", sequenceInType: 0, prompt: startFrame, status: "pending", characters: chars });
          savedCount++;
        }
        if (endFrame) {
          await insertAssetVersion({ shotId: shot.id, type: "last_frame", sequenceInType: 0, prompt: endFrame, status: "pending", characters: chars });
          savedCount++;
        }
      }
      console.log(`[KeyframePrompts Agent] Saved ${savedCount} assets from ${kpParsed.length} shots`);
      return NextResponse.json({ updatedCount: kpParsed.length, totalShots: kpAgentShots.length });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return NextResponse.json({ error: `智能体首尾帧提示词解析失败: ${msg}` }, { status: 422 });
    }
  }
  // === 智能体路由结束 ===

  if (!modelConfig?.text) {
    return NextResponse.json({ error: "No text model configured" }, { status: 400 });
  }

  let batchVersionId = payload?.versionId as string | undefined;
  if (!batchVersionId) {
    const [latestVer] = await db.select({ id: storyboardVersions.id })
      .from(storyboardVersions)
      .where(and(
        eq(storyboardVersions.projectId, projectId),
        ...(episodeId ? [eq(storyboardVersions.episodeId, episodeId)] : [])
      ))
      .orderBy(desc(storyboardVersions.versionNum))
      .limit(1);
    if (!latestVer?.id) return NextResponse.json({ error: "No version found. Run shot split first." }, { status: 400 });
    batchVersionId = latestVer.id;
  }
  const buildWhere = (includeVersion: boolean) => {
    const conds = [eq(shots.projectId, projectId)];
    if (includeVersion && batchVersionId) conds.push(eq(shots.versionId, batchVersionId));
    if (episodeId) conds.push(eq(shots.episodeId, episodeId));
    return and(...conds);
  };

  let allShots = await db
    .select()
    .from(shots)
    .where(buildWhere(true))
    .orderBy(asc(shots.sequence));

  if (allShots.length === 0 && batchVersionId) {
    console.warn(`[GenerateKeyframePrompts] strict filter empty (versionId=${batchVersionId}), falling back to no-version filter`);
    allShots = await db
      .select()
      .from(shots)
      .where(buildWhere(false))
      .orderBy(asc(shots.sequence));
  }

  if (allShots.length === 0) {
    return NextResponse.json({ error: "No shots found" }, { status: 400 });
  }

  const projectCharacters = await getEpisodeCharacters(projectId, episodeId);

  // Pull visual style meta from script (same regex as ref prompts handler)
  const scriptSource = episodeId
    ? await db.select({ script: episodes.script }).from(episodes).where(eq(episodes.id, episodeId))
    : await db.select({ script: projects.script }).from(projects).where(eq(projects.id, projectId));
  const script = scriptSource[0]?.script || "";

  const pickField = (label: string): string => {
    const re = new RegExp(`${label}[：:]\\s*(.+?)(?:\\n|$)`);
    const m = script.match(re);
    return m?.[1]?.trim() || "";
  };
  const visualStyle = [
    pickField("视觉风格") || pickField("Visual Style"),
    pickField("色彩基调") && `色彩基调：${pickField("色彩基调")}`,
    pickField("时代美学") && `时代美学：${pickField("时代美学")}`,
    pickField("氛围情绪") && `氛围情绪：${pickField("氛围情绪")}`,
    pickField("画幅比例") && `画幅比例：${pickField("画幅比例")}`,
  ].filter(Boolean).join("；");

  // Load character relationships — drives on-screen interaction framing.
  // Enemies must face each other as live combatants, not background icons.
  const kfRelations = await db
    .select()
    .from(characterRelations)
    .where(eq(characterRelations.projectId, projectId));
  let kfRelationsText = "";
  if (kfRelations.length > 0) {
    kfRelationsText = "\n\n## 角色关系（必须用于决定站位、眼神、肢体对抗、画面张力）\n";
    for (const rel of kfRelations) {
      const charA = projectCharacters.find((c) => c.id === rel.characterAId);
      const charB = projectCharacters.find((c) => c.id === rel.characterBId);
      if (charA && charB) {
        kfRelationsText += `- ${charA.name} ↔ ${charB.name}：${rel.relationType}${rel.description ? `（${rel.description}）` : ""}\n`;
      }
    }
    kfRelationsText += `
**关系驱动构图规则（最高优先级）**：
- **敌对 / 对立 / 仇人**：两人必须都是**活人角色同屏对峙**，直接对视、肢体对抗、武器对准彼此。严禁把任一方画成背景的雕像/神像/虚影/浮雕/壁画。
- **友好 / 盟友**：并肩站位、相互掩护、眼神交流。
- **爱慕 / 亲密**：靠近、牵手、拥抱、温柔对视。
- **父女 / 师徒**：长辈在前或侧，晚辈跟随。
- 凡是出现在 characters 列表里的角色，在首尾帧画面里都必须是真实的活人，不允许以雕像/虚影形式出场。
`;
  }

  const textProvider = resolveAIProvider(modelConfig);
  const keyframeSystemPrompt = await resolvePrompt("shot_split_keyframe_assets", {
    userId,
    projectId,
  });

  // Sequential per-shot generation: one LLM call at a time with immediate DB writes.
  const total = allShots.length;
  let doneCount = 0;
  console.log(`[GenerateKeyframePrompts] Starting sequential generation: 0/${total}`);
  let updatedCount = 0;

  for (const shot of allShots) {
    try {
      const basePromptRequest = buildKeyframePromptsRequest(
        [{
          sequence: shot.sequence,
          prompt: shot.prompt || "",
          motionScript: shot.motionScript,
          cameraDirection: shot.cameraDirection,
        }],
        projectCharacters.map((c) => ({
          name: c.name,
          description: c.description,
          visualHint: c.visualHint,
        })),
        visualStyle
      );
      const promptRequest = kfRelationsText
        ? basePromptRequest + kfRelationsText
        : basePromptRequest;

      const result = await textProvider.generateText(promptRequest, {
        systemPrompt: keyframeSystemPrompt,
        temperature: 0.5,
      });

      console.log(`[GenerateKeyframePrompts] Shot ${shot.sequence} raw response (first 800): ${result.slice(0, 800)}`);

      const jsonMatch = result.match(/\[[\s\S]*\]/);
      if (!jsonMatch) {
        throw new Error(`Shot ${shot.sequence}: invalid JSON response`);
      }
      const parsed = JSON.parse(jsonMatch[0]) as Array<{
        shotSequence: number;
        characters?: string[];
        prompts: string[];
      }>;
      const entry = parsed.find((e) => e.shotSequence === shot.sequence) || parsed[0];
      if (!entry || !Array.isArray(entry.prompts) || entry.prompts.length < 2) {
        throw new Error(`Shot ${shot.sequence}: expected 2 prompts (first/last frame)`);
      }

      const charsForShot = Array.isArray(entry.characters) ? entry.characters : [];
      await insertAssetVersion({
        shotId: shot.id,
        type: "first_frame",
        sequenceInType: 0,
        prompt: entry.prompts[0],
        status: "pending",
        characters: charsForShot,
      });
      await insertAssetVersion({
        shotId: shot.id,
        type: "last_frame",
        sequenceInType: 0,
        prompt: entry.prompts[1],
        status: "pending",
        characters: charsForShot,
      });
      doneCount++;
      updatedCount++;
      console.log(`[GenerateKeyframePrompts] ✓ shot ${shot.sequence} (${doneCount}/${total})`);
    } catch (err) {
      doneCount++;
      console.warn(`[GenerateKeyframePrompts] ✗ shot ${shot.sequence} (${doneCount}/${total}): ${String(err)}`);
    }
  }

  console.log(`[GenerateKeyframePrompts] Updated ${updatedCount}/${allShots.length} shots (sequential)`);
  return NextResponse.json({ updatedCount, totalShots: allShots.length });
}
