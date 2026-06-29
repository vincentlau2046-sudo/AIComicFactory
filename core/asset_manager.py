"""
core/asset_manager.py — 版本化资产管理器

ShotAsset 版本表实现：
  - 每次重生成插入新版本，旧版本标记 is_active=False
  - 文件命名: 自定义 dest_name 优先，否则 {shot_id}_{asset_type}_v{N}.{ext}
  - 旧版本文件自动清理（cleanup_old=True）
  - 持久化到 projects/{project}/assets.json

从 AICB ShotAsset 模型适配（见 PROJECT.md 5.4 节）。
"""

import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Literal

# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────

TZ = timezone(timedelta(hours=8))

AssetType = Literal[
    "character_ref",    # S3a: 单视图角色参考图
    "four_view",        # S3b: 四视图扩展
    "first_frame",      # S5: 首帧
    "last_frame",       # S5: 尾帧
    "keyframe_video",   # S6: FLF2V 视频片段
    "assembled_video",  # S7: 拼接视频
    "subtitled_video",  # S8: 字幕烧录版
    "final_video",      # S9: 最终成品
]


# ─────────────────────────────────────────────────────────────────
# AssetManager
# ─────────────────────────────────────────────────────────────────

class AssetManager:
    """版本化资产管理器。"""

    def __init__(self, projects_root: str = None):
        import os
        self.root = Path(projects_root or os.environ.get(
            "AICF_PROJECTS_ROOT",
            str(Path.home() / "AIComicFactory" / "projects")
        ))

    def _assets_path(self, project: str) -> Path:
        return self.root / project / "assets.json"

    # ─────────────────────────────────────────────────────────────
    # 底层读写
    # ─────────────────────────────────────────────────────────────

    def _read(self, project: str) -> dict:
        path = self._assets_path(project)
        if not path.exists():
            return {"project": project, "assets": [], "version_counter": {}}
        with open(path, "r") as f:
            return json.load(f)

    def _write(self, project: str, data: dict):
        path = self._assets_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ─────────────────────────────────────────────────────────────
    # 公开 API：注册资产
    # ─────────────────────────────────────────────────────────────

    def register(
        self,
        project: str,
        asset_type: AssetType,
        shot_id: Optional[str],
        source_path: Path,
        relative_dir: str,
        metadata: Optional[dict] = None,
        dest_name: Optional[str] = None,
        cleanup_old: bool = True,
    ) -> dict:
        """
        注册一个资产生成记录。

        参数:
            project:      项目名（如 "last_bento"）
            asset_type:   资产类型
            shot_id:      关联 shot（如 "shot_001"），角色图可为 None
            source_path:  源文件绝对路径（将被复制到项目目录）
            relative_dir: 项目内相对目录（如 "s5_frames"）
            metadata:     额外元数据（prompt/seed/model 等）
            dest_name:    自定义目标文件名（如 "老周.png"、"s01_first.png"）
                         若为 None 则使用版本化命名 {shot_prefix}_{asset_type}_v{N}.{ext}
            cleanup_old:  是否删除同一 asset 的旧版本文件（默认 True）

        返回:
            注册的 asset 记录
        """
        data = self._read(project)
        source_path = Path(source_path)

        ext = source_path.suffix.lstrip(".") or "png"
        category = f"{shot_id or 'char'}_{asset_type}"

        # Version counter
        counter_key = category
        version = data["version_counter"].get(counter_key, 0) + 1
        data["version_counter"][counter_key] = version

        # 目标文件名：自定义优先，否则版本化命名
        if dest_name:
            filename = dest_name
        else:
            shot_prefix = shot_id if shot_id else "char"
            filename = f"{shot_prefix}_{asset_type}_v{version}.{ext}"

        # 复制文件到项目目录
        dest_dir = self.root / project / relative_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename
        if source_path != dest_path:
            shutil.copy2(str(source_path), str(dest_path))

        # 清理旧版本文件 + 标记旧版本 inactive
        for a in data["assets"]:
            if a["asset_type"] == asset_type and a["shot_id"] == shot_id:
                if a["is_active"] and cleanup_old:
                    # 删除旧版本文件
                    old_path = self.root / project / a["file_path"]
                    if old_path.exists() and old_path != dest_path:
                        old_path.unlink(missing_ok=True)
                a["is_active"] = False

        # 新建版本记录
        now = datetime.now(TZ).isoformat()
        record = {
            "asset_type": asset_type,
            "shot_id": shot_id,
            "version": version,
            "is_active": True,
            "file_path": f"{relative_dir}/{filename}",
            "created_at": now,
            "metadata": metadata or {},
        }
        data["assets"].append(record)
        self._write(project, data)
        return record

    # ─────────────────────────────────────────────────────────────
    # 公开 API：查询
    # ─────────────────────────────────────────────────────────────

    def get_active(
        self, project: str, shot_id: str, asset_type: AssetType
    ) -> Optional[dict]:
        """获取活跃（最新有效）版本的资产记录。"""
        data = self._read(project)
        for a in reversed(data["assets"]):  # 后进先查，最新优先
            if (
                a["asset_type"] == asset_type
                and a["shot_id"] == shot_id
                and a["is_active"]
            ):
                return a
        return None

    def get_active_for_shot(
        self, project: str, shot_id: str
    ) -> List[dict]:
        """获取某个 shot 的所有活跃资产。"""
        data = self._read(project)
        return [
            a for a in data["assets"]
            if a["shot_id"] == shot_id and a["is_active"]
        ]

    def get_history(
        self, project: str, shot_id: str, asset_type: AssetType
    ) -> List[dict]:
        """获取某个资产的所有版本（含活跃和非活跃）。"""
        data = self._read(project)
        return [
            a for a in data["assets"]
            if a["asset_type"] == asset_type and a["shot_id"] == shot_id
        ]

    def get_character_active(
        self, project: str, character_name: str, asset_type: AssetType = "character_ref"
    ) -> Optional[dict]:
        """
        获取角色相关活跃资产。

        角色资产以 shot_id=None 存储，用 metadata.character 区分。
        """
        data = self._read(project)
        for a in reversed(data["assets"]):
            if (
                a["asset_type"] == asset_type
                and a.get("metadata", {}).get("character") == character_name
                and a["is_active"]
            ):
                return a
        return None

    # ─────────────────────────────────────────────────────────────
    # 公开 API：批量操作
    # ─────────────────────────────────────────────────────────────

    def invalidate_shot(self, project: str, shot_id: str):
        """标记某个 shot 的所有资产为无效。"""
        data = self._read(project)
        for a in data["assets"]:
            if a["shot_id"] == shot_id:
                a["is_active"] = False
        self._write(project, data)

    def list_project(self, project: str) -> dict:
        """返回项目的资管摘要。"""
        data = self._read(project)
        active = [a for a in data["assets"] if a["is_active"]]
        by_type: dict = {}
        for a in active:
            t = a["asset_type"]
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "project": project,
            "total_versions": len(data["assets"]),
            "active_assets": len(active),
            "by_type": by_type,
            "version_counter": data["version_counter"],
        }

    def export_report(self, project: str) -> str:
        """生成人类可读的资产报告。"""
        summary = self.list_project(project)
        data = self._read(project)

        lines = [f"Asset Report — {project}"]
        lines.append(f"  Total versions: {summary['total_versions']}")
        lines.append(f"  Active assets:  {summary['active_assets']}")
        lines.append(f"  By type:")
        for t, n in summary["by_type"].items():
            lines.append(f"    {t}: {n}")

        lines.append("")
        active_assets = [a for a in data["assets"] if a["is_active"]]
        for a in active_assets:
            shot = a.get("shot_id") or a.get("metadata", {}).get("character", "?")
            lines.append(
                f"  ✅ {a['asset_type']:20s} v{a['version']:<3d} {a['file_path']:40s} [{shot}]"
            )

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────

_DEFAULT = None


def get_asset_manager(projects_root: str = None) -> AssetManager:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = AssetManager(projects_root)
    return _DEFAULT
