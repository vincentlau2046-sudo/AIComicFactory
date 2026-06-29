"""prompts/defaults/__init__.py — Default prompt definitions"""

from prompts.defaults.script_parse import ScriptParsePrompt, build_script_parse
from prompts.defaults.character_extract import CharacterExtractPrompt, build_character_extract
from prompts.defaults.shot_split import ShotSplitPrompt, build_shot_split

__all__ = [
    "ScriptParsePrompt",
    "build_script_parse",
    "CharacterExtractPrompt",
    "build_character_extract",
    "ShotSplitPrompt",
    "build_shot_split",
]