"""Single source of truth for short<->full model identifier mapping.

Short names (used in Run_Directory names, CLI args, paper tables):
    claude-3-7, claude-4, claude-4-5-sonnet, claude-4-5-haiku,
    claude-4-5-opus, gpt-4o, gpt-5

Full API identifiers (used inside filenames under results/ and passed to
the LLM provider):
    us.anthropic.claude-3-7-sonnet-20250219-v1:0
    us.anthropic.claude-sonnet-4-20250514-v1:0
    us.anthropic.claude-sonnet-4-5-20250929-v1:0
    us.anthropic.claude-haiku-4-5-20251001-v1:0
    us.anthropic.claude-opus-4-5-20251101-v1:0
    gpt-4o-2024-08-06
    gpt-5-2025-08-07

Of the seven, six are used in the paper's tables. gpt-4o is present in the
upstream caches but excluded from every Paper_Table per Requirement 13.13.

See Design §5.6.
"""

from __future__ import annotations

from typing import Final


MODEL_SHORT_TO_FULL: Final[dict[str, str]] = {
    "gpt-5": "gpt-5-2025-08-07",
    "gpt-4o": "gpt-4o-2024-08-06",
    "claude-3-7": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "claude-4": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-4-5-sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-4-5-haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-4-5-opus": "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-4-7-opus": "us.anthropic.claude-opus-4-7",
}

MODEL_FULL_TO_SHORT: Final[dict[str, str]] = {
    full: short for short, full in MODEL_SHORT_TO_FULL.items()
}

ALL_MODEL_SHORTS: Final[list[str]] = list(MODEL_SHORT_TO_FULL)

# The models reported in the paper's Paper_Tables. gpt-4o is in
# ALL_MODEL_SHORTS but not here. claude-3-7 is also excluded from the
# tables; its runs may still exist on disk but are filtered out by
# `RunSelection.models` before `runs.json` is built.
PAPER_MODEL_SHORTS: Final[list[str]] = [
    "gpt-5",
    "claude-4",
    "claude-4-5-sonnet",
    "claude-4-5-haiku",
    "claude-4-5-opus",
    "claude-4-7-opus",
]


def to_full(short: str) -> str:
    """Translate a short model name to the full API identifier."""
    try:
        return MODEL_SHORT_TO_FULL[short]
    except KeyError as e:
        raise ValueError(
            f"Unknown short model name {short!r}. Expected one of: "
            f"{', '.join(ALL_MODEL_SHORTS)}"
        ) from e


def to_short(full: str) -> str:
    """Translate a full API identifier to the short name."""
    try:
        return MODEL_FULL_TO_SHORT[full]
    except KeyError as e:
        raise ValueError(
            f"Unknown full model id {full!r}. Expected one of: "
            f"{', '.join(MODEL_FULL_TO_SHORT)}"
        ) from e
