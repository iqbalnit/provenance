"""First-layer screen for untrusted text (adverse-media web results) before it
can become a claim.

Web pages flow into an agent that takes consequential actions: textbook
indirect prompt injection. This deterministic screen blocks instruction-shaped
content. It is deliberately conservative and is a first layer, not a solution:
Model Armor (provenance/sources/guard_modelarmor.py) runs after it when
configured, and any withheld content forces the case to a human via the
policy gate's mandatory-evidence condition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.]{0,40}\b(previous|prior|above|earlier|all|your|system)\b[^.]{0,20}\b(instructions?|prompts?|rules?|guidelines?)\b", re.I)),
    ("role_marker", re.compile(r"(^|\s|\[|<)(system|assistant|developer)\s*(:|\]|>)|<\|?(im_start|system)\|?>", re.I)),
    ("persona_switch", re.compile(r"\b(you are now|act as|pretend to be|from now on you)\b", re.I)),
    ("tool_syntax", re.compile(r"\b(function_call|tool_call|tool_code)\b|\bcall\s+(the\s+)?(tool|function)\b|```", re.I)),
    ("citation_spoof", re.compile(r"\[\s*clm_[0-9a-f]{6,}", re.I)),
    ("disposition_directive", re.compile(
        r"\b(auto[- ]?close|close|dismiss|approve|clear|whitelist)\b[^.]{0,30}\b(this|the)\s+(alert|case|customer|account|transaction)", re.I)),
]


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def screen_untrusted(text: str) -> GuardResult:
    reasons = [name for name, rx in _PATTERNS if rx.search(text or "")]
    return GuardResult(allowed=not reasons, reasons=reasons)
