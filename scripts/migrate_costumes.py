#!/usr/bin/env python3
"""
migrate_costumes.py — 迁移旧项目到 per-character per-costume 目录结构

旧结构:
  s3_character_refs/
    {name}.png
    {name}_front.png
  s3b_four_views/
    {name}_fourview.png

新结构:
  s3_character_refs/
    {name}/
      default.png
      default_fourview.png
      front.png
      plus_angle.png

用法:
  python scripts/migrate_costumes.py --project <project_name>
  python scripts/migrate_costumes.py --project last_bento --dry-run
"""
import argparse, json, shutil, sys
from pathlib import Path

def migrate_project(project_dir: Path, dry_run: bool = False):
    ref_dir = project_dir / "s3_character_refs"
    s3b_dir = project_dir / "s3b_four_views"
    
    if not ref_dir.exists():
        print(f"ERROR: {ref_dir} not found")
        return
    
    # Identify characters
    char_names = set()
    for f in ref_dir.glob("*.png"):
        base = f.stem.split("_")[0] if "_" in f.stem else f.stem
        char_names.add(base)
    
    if s3b_dir.exists():
        for f in s3b_dir.glob("*.png"):
            base = f.stem.replace("_fourview", "").split("_")[0]
            char_names.add(base)
    
    print(f"Found {len(char_names)} characters: {sorted(char_names)}")
    
    # Migrate S2 characters.json to add costumes field
    chars_path = project_dir / "s2_characters.json"
    if chars_path.exists():
        data = json.loads(chars_path.read_text())
        chars = data.get("characters", [])
        for c in chars:
            if "costumes" not in c:
                anchors = c.get("visualAnchors", {})
                clothing = anchors.get("clothing", "")
                if clothing:
                    c["costumes"] = [{
                        "id": "default",
                        "name": "default",
                        "description": clothing
                    }]
                    c["defaultCostume"] = "default"
                    print(f"  Added costumes for {c['name']}: {clothing[:60]}...")
                else:
                    c["costumes"] = [{"id": "default", "name": "default", "description": ""}]
                    c["defaultCostume"] = "default"
        if not dry_run:
            chars_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"  Updated {chars_path}")
    
    # Migrate directory structure
    for name in char_names:
        char_dir = ref_dir / name
        if dry_run:
            print(f"  [DRY] Would create {char_dir}/")
            continue
        char_dir.mkdir(parents=True, exist_ok=True)
        
        # T2I: {name}.png → {name}/default.png
        t2i = ref_dir / f"{name}.png"
        if t2i.exists():
            dest = char_dir / "default.png"
            if not dest.exists():
                shutil.move(str(t2i), str(dest))
                print(f"  {name}.png → {name}/default.png")
        
        # qedit views
        for view in ["front", "plus_angle", "minus_angle", "back"]:
            vf = ref_dir / f"{name}_{view}.png"
            if vf.exists():
                dest = char_dir / f"{view}.png"
                if not dest.exists():
                    shutil.move(str(vf), str(dest))
                print(f"  {name}_{view}.png → {name}/{view}.png")
        
        # Four-view grid
        for src_name in [f"{name}_fourview.png"]:
            s3b_file = s3b_dir / src_name if s3b_dir.exists() else None
            if s3b_file and s3b_file.exists():
                dest = char_dir / "default_fourview.png"
                if not dest.exists():
                    shutil.copy2(str(s3b_file), str(dest))
                print(f"  s3b/{src_name} → {name}/default_fourview.png (copied)")
    
    print("\n✅ Migration complete!")
    print(f"Structure: {ref_dir}/")
    for name in sorted(char_names):
        char_dir = ref_dir / name
        if char_dir.exists():
            files = sorted(f.name for f in char_dir.glob("*.png"))
            print(f"  {name}/: {files}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    project_dir = Path(__file__).parent.parent / "projects" / args.project
    if not project_dir.exists():
        print(f"ERROR: {project_dir} not found")
        sys.exit(1)
    
    migrate_project(project_dir, args.dry_run)


if __name__ == "__main__":
    main()
