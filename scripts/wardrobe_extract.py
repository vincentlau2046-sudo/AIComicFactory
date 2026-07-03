#!/usr/bin/env python3
"""
wardrobe_extract.py — 从 S2 角色描述中提取服饰，构建 costumes[] 衣橱

原则：
  - 零 LLM 依赖：纯提取 + 结构化，不从空气中创造服饰
  - 衣橱是角色描述的派生，不创造新信息
  - 支持手动扩展多套服饰（via --template 或直接编辑 JSON）

数据流：
  S2 description/visualAnchors.clothing (LLM 输出)
        ↓
  wardrobe_extract.py (纯提取)
        ↓
  costumes[] + defaultCostume (写入 s2_characters.json)
        ↓
  下游 S4/S5 消费

提取逻辑：
  1. 如果 costumes[] 已存在且非空 → 跳过（幂等）
  2. 否则从 visualAnchors.clothing 提取默认着装描述
  3. 生成 costumes: [{id: "default", name: "default", description: ...}]
  4. 写入 defaultCostume: "default"

用法：
  python scripts/wardrobe_extract.py --project last_bento
  python scripts/wardrobe_extract.py --project last_bento --force
  python scripts/wardrobe_extract.py --project last_bento --template  # 从模板扩展多套
"""
import argparse
import json
import sys
from pathlib import Path


def extract_clothing_from_description(description: str) -> str:
    """从角色视觉描述中提取服装部分。
    
    启发式策略：
    1. 查找包含服装关键词的段落段
    2. 提取"身穿/穿着/上身/下身/脚穿"等动词引导的服饰描述
    3. 回退：提取标点分段中找到的服装关键词组合
    """
    clothing_keywords = [
        "上装", "下装", "脚穿", "鞋子", "外套", "夹克", "T恤", "衬衫",
        "裤子", "裙子", "鞋", "靴", "帽", "围巾", "手套", "腰带", "配饰",
        "工装", "制服", "毛衣", "大衣", "西装", "连衣裙", "旗袍",
        "身穿", "身着", "穿着", "外穿", "内搭",
    ]
    
    # Strategy 1: find sentences with clothing keywords
    sentences = description.replace("。", "。\n").split("\n")
    clothing_sentences = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if any(kw in s for kw in clothing_keywords):
            clothing_sentences.append(s)
    
    if clothing_sentences:
        return "，".join(clothing_sentences)
    
    # Strategy 2: take the "4. 服装" section if present
    for marker in ["服装——", "服装：", "着装——", "着装："]:
        idx = description.find(marker)
        if idx >= 0:
            section = description[idx + len(marker):]
            # Stop at next numbered section or end of clothing description
            for end_marker in ["。", "角色色彩", "5.", "6.", "7.", "8."]:
                end_idx = section.find(end_marker)
                if end_idx > 10:
                    section = section[:end_idx]
                    break
            return section.strip()
    
    # Strategy 3: fallback — return the full description is only reliable for well-structured ones
    return description


def extract_wardrobe(characters: list, force: bool = False) -> tuple[list, list]:
    """为每个角色提取衣橱。
    
    Returns: (updated_characters, log_lines)
    """
    log = []
    updated_chars = []
    
    for c in characters:
        name = c.get("name", "?")
        existing = c.get("costumes")
        
        # Idempotent: skip if already has non-empty costumes
        if existing and len(existing) > 0 and not force:
            log.append(f"  {name}: 已有 {len(existing)} 套服饰 — 跳过")
            updated_chars.append(c)
            continue
        
        # Extract clothing
        anchors = c.get("visualAnchors", {})
        clothing = anchors.get("clothing", "").strip()
        
        if not clothing:
            # Try extracting from description
            desc = c.get("description", "")
            clothing = extract_clothing_from_description(desc)
        
        if not clothing:
            log.append(f"  {name}: ❌ 无可用服饰描述")
            # Still add empty costumes for schema completeness
            c["costumes"] = [{"id": "default", "name": "default", "description": ""}]
            c["defaultCostume"] = "default"
            updated_chars.append(c)
            continue
        
        # Build default costume entry
        c["costumes"] = [{
            "id": "default",
            "name": "默认着装",
            "description": clothing,
        }]
        c["defaultCostume"] = "default"
        
        log.append(f"  {name}: ✅ 提取 1 套服饰 — {clothing[:60]}...")
        updated_chars.append(c)
    
    return updated_chars, log


def extend_wardrobe_from_template(characters: list) -> tuple[list, list]:
    """从预设模板为角色扩展多套服饰（可选）。
    
    模板提供常见换装场景对应的服饰描述框架。
    仅当角色已有 default 服饰时扩展。
    """
    templates = {
        "工地工人": {
            "casual": {"name": "日常便装", "description": "灰色圆领毛衣，深蓝色直筒牛仔裤，白色运动鞋"},
            "formal": {"name": "出门正装", "description": "深色夹克外套，白色衬衫，黑色长裤，棕色皮鞋"},
        },
        "摊贩/餐饮": {
            "casual": {"name": "家居便装", "description": "浅色棉质家居服，宽松长裤，拖鞋"},
            "festive": {"name": "节日着装", "description": "红色开衫，深色长裤，黑色皮鞋"},
        },
        "年轻工人": {
            "casual": {"name": "休闲便装", "description": "白色T恤，浅蓝色牛仔裤，白色帆布鞋"},
            "sport": {"name": "运动装", "description": "黑色运动卫衣，灰色运动裤，跑步鞋"},
        },
    }
    
    log = []
    updated = []
    
    for c in characters:
        name = c.get("name", "?")
        occupations = ["工地工人", "摊贩/餐饮", "年轻工人"]
        
        matched_template = None
        for occ, tpl in templates.items():
            desc = c.get("description", "") + c.get("visualAnchors", {}).get("clothing", "")
            if any(kw in desc for kw in occ.split("/")):
                matched_template = tpl
                break
        
        if matched_template:
            existing = c.get("costumes", [])
            existing_ids = {e["id"] for e in existing}
            added = 0
            for cid, cinfo in matched_template.items():
                if cid not in existing_ids:
                    existing.append({"id": cid, "name": cinfo["name"], "description": cinfo["description"]})
                    added += 1
            if added:
                c["costumes"] = existing
                log.append(f"  {name}: ✅ 扩展 +{added} 套（模板={occ}）")
            else:
                log.append(f"  {name}: 模板已存在 — 跳过")
        else:
            log.append(f"  {name}: 无匹配模板 — 保持现有")
        
        updated.append(c)
    
    return updated, log


def main():
    parser = argparse.ArgumentParser(description="从 S2 角色描述提取衣橱")
    parser.add_argument("--project", "-P", required=True, help="项目名")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有 costumes")
    parser.add_argument("--template", action="store_true", help="使用预设模板扩展多套服饰")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    project_dir = Path(__file__).parent.parent / "projects" / args.project
    chars_path = project_dir / "s2_characters.json"
    
    if not chars_path.exists():
        print(f"❌ {chars_path} 不存在，请先跑 S2 character_extract")
        sys.exit(1)
    
    data = json.loads(chars_path.read_text())
    chars = data.get("characters", [])
    
    if not chars:
        print("❌ 无角色数据")
        sys.exit(1)
    
    print(f"项目: {args.project}")
    print(f"角色: {len(chars)} 个\n")
    
    if args.template:
        print("📋 从预设模板扩展多套服饰...")
        updated, log = extend_wardrobe_from_template(chars)
    else:
        print("👗 从 description 提取默认服饰...")
        updated, log = extract_wardrobe(chars, force=args.force)
    
    for line in log:
        print(line)
    
    if not args.dry_run:
        data["characters"] = updated
        chars_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"\n✅ 写入 {chars_path}")
    else:
        print(f"\n[Dry run] 未写入 {chars_path}")


if __name__ == "__main__":
    main()