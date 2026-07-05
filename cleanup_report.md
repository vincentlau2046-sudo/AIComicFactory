# Cleanup Report — 2026-07-05

## Summary
Deleted 3 deprecated scripts and cleaned up all references across the codebase.

## Deleted Files

| File | Reason |
|------|--------|
| `scripts/s6_video_assemble.py` | Fully replaced by `scripts/s7_video_assemble.py` (old Ken Burns-based S6+S7 combine) |
| `scripts/gen_prompts.py` | Replaced by `core/prompt_runner.py` (hardcoded last_bento test script) |
| `scripts/gen_s4_shots.py` | Hardcoded last_bento-specific test script; S4 now runs via Nova (LLM) only |

## Reference Cleanup

### Files checked — no references found
- `pipeline.yaml` ✅
- `scripts/e2e_dry_run.py` ✅
- `core/state_manager.py` ✅
- `SKILL.md` ✅
- `PROJECT.md` ✅
- `tests/` (26 files) ✅

### Files updated
- **`README.md`**: Updated S4 table entry (removed `gen_s4_shots.py`); removed `gen_prompts.py` step from usage instructions
- **`docs/audits/f1-narrative-quality.md`**: Annotated 7 references to `gen_prompts.py` / `gen_s4_shots.py` as deleted
- **`docs/audits/f4-video-coherence.md`**: Annotated 1 reference to `s6_video_assemble.py` as deleted

## Verification Checklist

- [x] `grep -r "gen_prompts\|s6_video_assemble\|gen_s4_shots" ~/AIComicFactory/` — only audit docs with `~~strikethrough~~ *(已删除)*` annotations remain
- [x] Deleted files no longer exist on disk
- [x] Scripts removed via `git rm` (proper VCS tracking)
