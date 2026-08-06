import ffmpeg from "fluent-ffmpeg";
import fs from "node:fs";
import path from "node:path";
import { id as genId } from "@/lib/id";

const uploadDir = process.env.UPLOAD_DIR || "./uploads";

type TransitionType = "cut" | "dissolve" | "fade_in" | "fade_out" | "wipeleft" | "slideright" | "circleopen";

const DEFAULT_XFADE_DURATION = 0.5;

interface SubtitleEntry {
  text: string;
  shotSequence: number;
  dialogueSequence: number;  // 0-based index within the shot
  dialogueCount: number;     // total dialogues in this shot
  startRatio?: number;       // 0-1, when dialogue starts relative to shot duration
  endRatio?: number;         // 0-1, when dialogue ends relative to shot duration
}

interface AssembleParams {
  videoPaths: string[];
  subtitles: SubtitleEntry[];
  projectId: string;
  shotDurations: number[];
  transitions?: TransitionType[]; // transition between shot[i] and shot[i+1], length = videoPaths.length - 1
  titleCard?: { text: string; duration: number };
  creditsCard?: { text: string; duration: number };
  bgmPath?: string;
  bgmVolume?: number; // 0.0-1.0, default 0.3
}

interface AssembleResult {
  videoPath: string;
  srtPath?: string;
}

export async function generateTitleCard(
  text: string,
  duration: number,
  outputDir: string,
  options?: { fontSize?: number; bgColor?: string; textColor?: string }
): Promise<string> {
  const { fontSize = 48, bgColor = "black", textColor = "white" } = options || {};
  const cardPath = path.resolve(outputDir, `title-${genId()}.mp4`);

  await new Promise<void>((resolve, reject) => {
    ffmpeg()
      .input(`color=c=${bgColor}:s=1920x1080:d=${duration}`)
      .inputOptions(["-f", "lavfi"])
      .outputOptions([
        "-vf",
        `drawtext=text='${text.replace(/'/g, "'\\''")}':fontsize=${fontSize}:fontcolor=${textColor}:x=(w-text_w)/2:y=(h-text_h)/2`,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-t", String(duration),
        "-pix_fmt", "yuv420p",
      ])
      .output(cardPath)
      .on("end", () => resolve())
      .on("error", (err) => reject(new Error(`Title card generation failed: ${err.message}`)))
      .run();
  });

  return cardPath;
}

function generateSrtFile(
  subtitles: SubtitleEntry[],
  shotDurations: number[],
  outputPath: string
): string {
  const srtPath = outputPath.replace(/\.mp4$/, ".srt");

  const shotStartTimes: number[] = [];
  let cumulative = 0;
  for (const duration of shotDurations) {
    shotStartTimes.push(cumulative);
    cumulative += duration;
  }

  const srtEntries: string[] = [];
  let index = 1;

  for (const sub of subtitles) {
    const shotIdx = sub.shotSequence - 1;
    if (shotIdx < 0 || shotIdx >= shotDurations.length) continue;

    const shotStart = shotStartTimes[shotIdx];
    const shotDur = shotDurations[shotIdx];

    let startTime: number;
    let endTime: number;

    if (sub.startRatio !== undefined && sub.endRatio !== undefined) {
      // Use explicit timing ratios from DB
      startTime = shotStart + shotDur * sub.startRatio;
      endTime = shotStart + shotDur * sub.endRatio;
    } else {
      // Auto-distribute: divide shot duration equally among dialogues
      const segmentDur = shotDur / sub.dialogueCount;
      startTime = shotStart + segmentDur * sub.dialogueSequence;
      endTime = startTime + segmentDur;
    }

    srtEntries.push(
      `${index}\n${formatSrtTime(startTime)} --> ${formatSrtTime(endTime)}\n${sub.text}\n`
    );
    index++;
  }

  fs.writeFileSync(srtPath, srtEntries.join("\n"));
  return srtPath;
}

function formatSrtTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
}

// Escape path for ffmpeg subtitles filter (colon, backslash, single quote)
function escapeSubtitlePath(p: string): string {
  return p.replace(/\\/g, "/").replace(/:/g, "\\:").replace(/'/g, "'\\''");
}

/** Map our transition type to ffmpeg xfade transition name */
function mapTransitionName(t: TransitionType): string {
  if (t === "fade_in" || t === "fade_out") return "fade";
  return t;
}

/**
 * Concatenate videos with optional xfade transitions.
 * Returns the path to the concatenated output file.
 */
async function concatWithTransitions(
  videoPaths: string[],
  transitions: TransitionType[],
  shotDurations: number[],
  outputPath: string,
  projectId: string,
  outputDir: string,
): Promise<void> {
  // Single video: just copy
  if (videoPaths.length === 1) {
    fs.copyFileSync(path.resolve(videoPaths[0]), outputPath);
    return;
  }

  // All cuts: use fast concat demuxer
  const allCuts = transitions.every((t) => t === "cut");
  if (allCuts) {
    const concatListPath = path.resolve(outputDir, `${projectId}-concat.txt`);
    const concatContent = videoPaths
      .map((p) => `file '${path.resolve(p)}'`)
      .join("\n");
    fs.writeFileSync(concatListPath, concatContent);

    await new Promise<void>((resolve, reject) => {
      ffmpeg()
        .input(concatListPath)
        .inputOptions(["-f", "concat", "-safe", "0"])
        .outputOptions(["-c", "copy"])
        .output(outputPath)
        .on("end", () => {
          fs.unlinkSync(concatListPath);
          resolve();
        })
        .on("error", (err) => {
          reject(new Error(`FFmpeg concat failed: ${err.message}`));
        })
        .run();
    });
    return;
  }

  // Mixed transitions: use xfade filter chain
  const cmd = ffmpeg();
  for (const vp of videoPaths) {
    cmd.input(path.resolve(vp));
  }

  // Build xfade filter chain
  const filterParts: string[] = [];
  let prevLabel = "0:v";
  let cumulativeOffset = 0;

  for (let i = 0; i < transitions.length; i++) {
    const t = transitions[i];
    const duration = shotDurations[i];
    const outLabel = i < transitions.length - 1 ? `v${i}` : "vout";

    if (t === "cut") {
      // For cut: use xfade with duration=0 to simulate hard cut
      const offset = cumulativeOffset + duration;
      filterParts.push(
        `[${prevLabel}][${i + 1}:v]xfade=transition=fade:duration=0:offset=${offset.toFixed(3)}[${outLabel}]`
      );
      cumulativeOffset = offset;
    } else {
      const xfadeDur = DEFAULT_XFADE_DURATION;
      const offset = cumulativeOffset + duration - xfadeDur;
      const xfadeName = mapTransitionName(t);
      filterParts.push(
        `[${prevLabel}][${i + 1}:v]xfade=transition=${xfadeName}:duration=${xfadeDur}:offset=${offset.toFixed(3)}[${outLabel}]`
      );
      cumulativeOffset = offset;
    }

    prevLabel = outLabel;
  }

  const complexFilter = filterParts.join(";");

  await new Promise<void>((resolve, reject) => {
    cmd
      .complexFilter(complexFilter, "vout")
      .outputOptions([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-an",
      ])
      .output(outputPath)
      .on("end", () => resolve())
      .on("error", (err) => {
        reject(new Error(`FFmpeg xfade concat failed: ${err.message}`));
      })
      .run();
  });
}

export async function assembleVideo(params: AssembleParams): Promise<AssembleResult> {
  const { subtitles, projectId } = params;
  const allPaths = [...params.videoPaths];
  const allDurations = [...params.shotDurations];

  const outputDir = path.resolve(uploadDir, "videos");
  fs.mkdirSync(outputDir, { recursive: true });

  // Prepend title card if specified
  if (params.titleCard) {
    const titlePath = await generateTitleCard(
      params.titleCard.text,
      params.titleCard.duration,
      outputDir
    );
    allPaths.unshift(titlePath);
    allDurations.unshift(params.titleCard.duration);
  }

  // Append credits card if specified
  if (params.creditsCard) {
    const creditsPath = await generateTitleCard(
      params.creditsCard.text,
      params.creditsCard.duration,
      outputDir
    );
    allPaths.push(creditsPath);
    allDurations.push(params.creditsCard.duration);
  }

  const transitions: TransitionType[] = params.transitions
    ?? new Array(Math.max(allPaths.length - 1, 0)).fill("cut");

  const concatOutputPath = path.resolve(outputDir, `${projectId}-concat-${genId()}.mp4`);
  const outputPath = path.resolve(outputDir, `${projectId}-final-${genId()}.mp4`);

  // Step 1: Concatenate video clips (with transitions)
  await concatWithTransitions(allPaths, transitions, allDurations, concatOutputPath, projectId, outputDir);

  // Step 2: Burn in subtitles if any
  let srtPath: string | undefined;
  if (subtitles.length > 0) {
    srtPath = generateSrtFile(subtitles, allDurations, outputPath);
    const escapedSrtPath = escapeSubtitlePath(path.resolve(srtPath));

    try {
      await new Promise<void>((resolve, reject) => {
        ffmpeg()
          .input(concatOutputPath)
          .outputOptions([
            "-y",
            "-vf", `subtitles='${escapedSrtPath}'`,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
          ])
          .output(outputPath)
          .on("end", () => {
            fs.unlinkSync(concatOutputPath);
            // Keep SRT file for external subtitle export
            resolve();
          })
          .on("error", (err) => {
            reject(err);
          })
          .run();
      });
    } catch (err) {
      // Fallback: skip subtitle burn, use concat output directly
      console.warn(`[FFmpeg] Subtitle burn failed, using concat output: ${err}`);
      fs.renameSync(concatOutputPath, outputPath);
    }
  } else {
    // No subtitles, just rename
    fs.renameSync(concatOutputPath, outputPath);
  }

  // Step 3: Mix background music if provided
  if (params.bgmPath && fs.existsSync(path.resolve(params.bgmPath))) {
    const bgmOutputPath = outputPath.replace(/\.mp4$/, `-bgm.mp4`);
    const vol = params.bgmVolume ?? 0.3;

    try {
      await new Promise<void>((resolve, reject) => {
        ffmpeg()
          .input(outputPath)
          .input(path.resolve(params.bgmPath!))
          .outputOptions([
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-af", `volume=${vol}`,
            "-shortest",
          ])
          .output(bgmOutputPath)
          .on("end", () => {
            fs.unlinkSync(outputPath);
            fs.renameSync(bgmOutputPath, outputPath);
            resolve();
          })
          .on("error", (err) => reject(err))
          .run();
      });
    } catch (err) {
      console.warn(`[FFmpeg] BGM mix failed, skipping: ${err}`);
    }
  }

  // Return relative paths for uploadUrl compatibility
  return {
    videoPath: path.relative(process.cwd(), outputPath),
    srtPath: srtPath ? path.relative(process.cwd(), srtPath) : undefined,
  };
}
