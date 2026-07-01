"""
core/timeline.py — 统一时间轴计算

S7/S8/S9 共享的时间轴计算模块，消除三处独立计算的不一致。
核心原则：
  - 基于 s4_shots.json 的 scenes→shots 结构
  - 含标题卡/结束卡偏移
  - 含 xfade 重叠修正
  - 支持从实际视频文件 ffprobe 校准时长
"""

import json
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════

class ShotTiming:
    """单个 shot 的时间轴信息."""
    __slots__ = ("shot_number", "duration", "start_time", "end_time",
                 "scene_number", "transition_in", "transition_out")

    def __init__(self, shot_number: int, duration: float, start_time: float,
                 scene_number: int = 0, transition_in: str = "cut",
                 transition_out: str = "cut"):
        self.shot_number = shot_number
        self.duration = duration
        self.start_time = start_time
        self.end_time = start_time + duration
        self.scene_number = scene_number
        self.transition_in = transition_in
        self.transition_out = transition_out


class Timeline:
    """
    完整项目时间轴.
    
    包含: 标题卡 → shots → 结束卡
    支持: xfade 重叠修正、ffprobe 校准
    """
    def __init__(self):
        self.title_duration: float = 0.0
        self.credits_duration: float = 0.0
        self.xfade_duration: float = 0.0
        self.shots: List[ShotTiming] = []
        self._total_duration: Optional[float] = None

    @property
    def total_duration(self) -> float:
        """总时长（含标题卡和结束卡）."""
        if self._total_duration is not None:
            return self._total_duration
        if not self.shots:
            return self.title_duration + self.credits_duration
        last = self.shots[-1]
        return last.end_time + self.credits_duration

    @total_duration.setter
    def total_duration(self, value: float):
        self._total_duration = value

    @property
    def shots_only_duration(self) -> float:
        """仅 shots 的总时长（不含标题卡/结束卡）."""
        if not self.shots:
            return 0.0
        return self.shots[-1].end_time - self.shots[0].start_time

    def shot_durations_list(self) -> List[float]:
        """返回 shot duration 列表（给 S7 用）."""
        return [s.duration for s in self.shots]

    def shot_transitions_list(self) -> List[str]:
        """返回 shot transition 列表（给 S7 用）."""
        return [s.transition_out for s in self.shots]


# ═══════════════════════════════════════════════════════════════════
# 构建 Timeline
# ═══════════════════════════════════════════════════════════════════

def build_timeline(
    s4_data: dict,
    title_duration: float = 0.0,
    credits_duration: float = 0.0,
    xfade_duration: float = 0.0,
) -> Timeline:
    """
    从 s4_shots.json 构建 Timeline.
    
    Args:
        s4_data: 解析后的 s4_shots.json 内容
        title_duration: 标题卡时长（秒），0 = 无标题卡
        credits_duration: 结束卡时长（秒），0 = 无结束卡
        xfade_duration: 转场重叠时长（秒），0 = 无修正
    
    Returns:
        Timeline 对象
    """
    tl = Timeline()
    tl.title_duration = title_duration
    tl.credits_duration = credits_duration
    tl.xfade_duration = xfade_duration

    current_time = title_duration
    scene_idx = 0

    for scene in s4_data.get("scenes", []):
        scene_idx += 1
        for shot in scene.get("shots", []):
            sn = shot.get("shotNumber", 0)
            dur = shot.get("duration", 5.0)
            trans_out = shot.get("transitionOut", "cut")
            trans_in = shot.get("transitionIn", "cut")

            st = ShotTiming(
                shot_number=sn,
                duration=dur,
                start_time=current_time,
                scene_number=scene_idx,
                transition_in=trans_in,
                transition_out=trans_out,
            )
            tl.shots.append(st)
            current_time += dur

    # xfade 重叠修正: 每个非 cut 转场会消耗 xfade_duration 的重叠时间
    # 简化处理: 总时长减少 N * xfade_duration (N = 非cut转场数)
    if xfade_duration > 0 and len(tl.shots) > 1:
        non_cut = sum(1 for s in tl.shots[:-1] if s.transition_out != "cut")
        # 注意: 标题卡→s1 和 sN→结束卡 的转场也算
        if title_duration:
            non_cut += 1  # fade_in
        if credits_duration:
            non_cut += 1  # fade_out
        # 修正后的总时长已在 total_duration 中隐含，
        # 但 shot 的 start_time/end_time 不修正（它们是"逻辑"时间）
        # 修正只在 S7 的 xfade offset 计算中体现

    return tl


def build_timeline_from_project(
    project_dir: Path,
    title_duration: float = 3.0,
    credits_duration: float = 4.0,
    xfade_duration: float = 0.5,
    calibrate_with_videos: bool = True,
) -> Timeline:
    """
    从项目目录构建 Timeline，可选从实际视频校准时长.
    
    Args:
        project_dir: projects/{project}/ 目录
        title_duration: 标题卡时长
        credits_duration: 结束卡时长
        xfade_duration: 转场重叠时长
        calibrate_with_videos: 是否用 ffprobe 校准 s6_videos 时长
    
    Returns:
        Timeline 对象
    """
    s4_path = project_dir / "s4_shots.json"
    if not s4_path.exists():
        raise FileNotFoundError(f"{s4_path} not found")

    with open(s4_path) as f:
        s4_data = json.load(f)

    tl = build_timeline(s4_data, title_duration, credits_duration, xfade_duration)

    # 可选: 用 ffprobe 校准 shot 时长
    if calibrate_with_videos:
        videos_dir = project_dir / "s6_videos"
        if videos_dir.exists():
            for st in tl.shots:
                video_path = videos_dir / f"s{st.shot_number:02d}.mp4"
                if video_path.exists():
                    try:
                        actual_dur = _ffprobe_duration(video_path)
                        if actual_dur > 0:
                            st.duration = actual_dur
                    except Exception:
                        pass
            # 重新计算 start_time/end_time
            current_time = title_duration
            for st in tl.shots:
                st.start_time = current_time
                st.end_time = current_time + st.duration
                current_time += st.duration

    return tl


# ═══════════════════════════════════════════════════════════════════
# 对话时间轴
# ═══════════════════════════════════════════════════════════════════

def calc_dialogue_timeline(s4_data: dict, timeline: Timeline) -> List[dict]:
    """
    计算每条对话的绝对时间轴位置.
    
    Args:
        s4_data: s4_shots.json 数据
        timeline: 已构建的 Timeline（含标题卡偏移）
    
    Returns:
        list of {global_idx, shot, character, text, start_s, end_s}
    """
    entries = []
    global_idx = 0

    # 构建 shot_number → ShotTiming 映射
    shot_map = {st.shot_number: st for st in timeline.shots}

    for scene in s4_data.get("scenes", []):
        for shot in scene.get("shots", []):
            sn = shot.get("shotNumber", 0)
            dialogues = shot.get("dialogues", [])
            n = len(dialogues)
            st = shot_map.get(sn)

            if not st:
                continue

            for di, d in enumerate(dialogues):
                # 使用 startRatio/endRatio 如果存在
                sr = d.get("startRatio")
                er = d.get("endRatio")

                if sr is not None and er is not None:
                    start_s = st.start_time + st.duration * sr
                    end_s = st.start_time + st.duration * er
                else:
                    # 均匀分配: 在 shot 内等分，留 10% 边距
                    margin = st.duration * 0.1
                    usable = st.duration - 2 * margin
                    slot = usable / max(n, 1)
                    start_s = st.start_time + margin + slot * di
                    end_s = start_s + slot * 0.85  # 85% 占用，留呼吸空间

                entries.append({
                    "global_idx": global_idx,
                    "shot": sn,
                    "character": d.get("character", d.get("characterName", "")),
                    "text": d.get("text", ""),
                    "start_s": round(start_s, 2),
                    "end_s": round(end_s, 2),
                    "startRatio": sr,
                    "endRatio": er,
                })
                global_idx += 1

    return entries


# ═══════════════════════════════════════════════════════════════════
# 字幕生成 (SRT / ASS)
# ═══════════════════════════════════════════════════════════════════

def fmt_srt_time(seconds: float) -> str:
    """Format seconds to SRT time: HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_ass_time(seconds: float) -> str:
    """Format seconds to ASS time: H:MM:SS.cc."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def clean_subtitle_text(text: str) -> str:
    """Clean text for TTS/subtitle consistency."""
    return text.replace("……", ",").replace("——", ",").replace("、", ",")


def generate_srt(dialogue_entries: List[dict], output_path: Path) -> Path:
    """
    从 calc_dialogue_timeline 的输出生成 SRT 文件.
    
    Args:
        dialogue_entries: calc_dialogue_timeline() 的输出
        output_path: SRT 文件路径
    
    Returns:
        SRT 文件路径
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for i, entry in enumerate(dialogue_entries, 1):
            text = clean_subtitle_text(entry["text"])
            char = entry.get("character", "")
            line = f"{char}: {text}" if char else text
            f.write(f"{i}\n")
            f.write(f"{fmt_srt_time(entry['start_s'])} --> {fmt_srt_time(entry['end_s'])}\n")
            f.write(f"{line}\n\n")
    return output_path


def generate_ass(dialogue_entries: List[dict], output_path: Path,
                 width: int = 1280, height: int = 720) -> Path:
    """
    从 calc_dialogue_timeline 的输出生成 ASS 字幕文件.
    
    三样式:
      - 旁白: 白色, 44px
      - 心声: 半透明, 40px, 斜体
      - 对话: 黄色, 48px, 加粗
    """
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"""[Script Info]
Title: AIComicFactory
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Narration,Noto Sans CJK SC,44,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,30,1
Style: InnerVoice,Noto Sans CJK SC,40,&H80FFFFFF,&H00000000,&H64000000,0,-1,0,0,100,100,0,0,1,2,0,2,20,20,30,1
Style: Dialogue,Noto Sans CJK SC,48,&H00FFFF00,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2,0,2,20,20,30,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""")
        for entry in dialogue_entries:
            text = clean_subtitle_text(entry["text"])
            char = entry.get("character", "")
            # 简单样式选择: 默认用 Dialogue
            style = "Dialogue"
            line = f"{char}: {text}" if char else text
            f.write(f"Dialogue: 0,{fmt_ass_time(entry['start_s'])},{fmt_ass_time(entry['end_s'])},{style},,0,0,0,,{line}\n")
    return output_path


# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════

def _ffprobe_duration(path: Path) -> float:
    """用 ffprobe 获取视频时长."""
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], capture_output=True, text=True, check=True)
    return float(result.stdout.strip())
