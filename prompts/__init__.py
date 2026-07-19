from __future__ import annotations

import re
from pathlib import Path


PROMPT_ROOT = Path(__file__).parent
PROMPT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_prompt(name: str, version: str) -> str:
    if not PROMPT_NAME.fullmatch(name) or not PROMPT_NAME.fullmatch(version):
        raise ValueError("Prompt names and versions must use lowercase letters, numbers, and hyphens.")
    path = PROMPT_ROOT / f"{name}.{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path.name}")
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Prompt is empty: {path.name}")
    return prompt
