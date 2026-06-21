"""Token estimation module v0.2.0 — unified CJK/Latin heuristic token counting.

This is the canonical implementation across the judicial-mcp ecosystem.
Covers CJK ideographs, CJK punctuation, and fullwidth characters —
the most complete version as identified in the cross-project comparison.

Bridge Architecture: NO LLM calls.
"""

import logging

logger = logging.getLogger(__name__)

# ── Heuristic constants ────────────────────────────────────────
_CHARS_PER_TOKEN_ZH = 1.5   # ~1.5 Chinese chars per token (cl100k_base avg)
_CHARS_PER_TOKEN_EN = 4.0   # ~4.0 English chars per token


def estimate_tokens(text: str) -> int:
    """CJK/Latin mixed heuristic token estimation.

    Covers three Unicode ranges that the original quality-mcp missed:
      - \\u3000-\\u303f : CJK punctuation (、。〈〉《》「」 etc.)
      - \\uff00-\\uffef : Fullwidth forms (Ａ-Ｚ ａ-ｚ ０-９ etc.)
      - \\u4e00-\\u9fff : CJK Unified Ideographs (original coverage)

    This matches the hallucination-mcp implementation which was identified
    as the most accurate in the cross-project comparison (MCP-COMPARE-20260601).
    """
    cjk_count = 0
    for ch in text:
        if ('\u4e00' <= ch <= '\u9fff' or    # CJK Unified Ideographs
            '\u3000' <= ch <= '\u303f' or      # CJK Symbols and Punctuation
            '\uff00' <= ch <= '\uffef'):       # Fullwidth Forms
            cjk_count += 1
    non_cjk = len(text) - cjk_count
    return int(cjk_count / _CHARS_PER_TOKEN_ZH + non_cjk / _CHARS_PER_TOKEN_EN)


def estimate_token_budget(
    *,
    char_count: int,
    chars_per_token_zh: float = _CHARS_PER_TOKEN_ZH,
    chars_per_token_en: float = _CHARS_PER_TOKEN_EN,
) -> int:
    """Estimate token count from a raw character count (no text available).

    Uses a blended ratio assuming mixed CJK/Latin content.
    """
    blended = (chars_per_token_zh + chars_per_token_en) / 2
    return int(char_count / blended)
