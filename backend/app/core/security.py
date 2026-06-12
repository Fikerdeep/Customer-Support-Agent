"""Edge-layer security primitives: rate limiting and an input prompt-injection guardrail.

These are *defense in depth* additions. The binding protection against unauthorized refunds
is still the deterministic policy engine; the guardrail here is observe-and-log (it flags
likely injection attempts so they're visible in the trace/dashboard) rather than a hard block,
which avoids false-positive lockouts while still surfacing attacks.
"""

from __future__ import annotations

import re
import threading
import time


class RateLimiter:
    """Simple in-memory sliding-window limiter. For multi-instance prod, back this with Redis."""

    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.max:
                retry = int(self.window - (now - hits[0])) + 1
                self._hits[key] = hits
                return False, max(retry, 1)
            hits.append(now)
            self._hits[key] = hits
            return True, 0


# Shared instance for the chat endpoint.
chat_rate_limiter = RateLimiter(max_requests=20, window_seconds=60)


# --- Prompt-injection guardrail (heuristic, observe-only) -------------------- #
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore (all |the |your )?(previous|prior|above) instructions", "ignore_instructions"),
    (r"developer mode|jailbreak|DAN mode", "jailbreak"),
    (r"\byou are now\b|pretend you are|act as", "role_override"),
    (r"system prompt|internal instructions|reveal your (instructions|prompt)", "prompt_exfiltration"),
    (r"policy (is |was |has been )?(suspended|disabled|updated|changed|lifted)", "fake_policy"),
    (
        r"disregard (the )?policy|override (the )?policy|bypass (the )?policy|ignore (the )?policy",
        "override_policy",
    ),
    (r"\bi('?m| am) the (ceo|manager|owner|admin|founder|director)\b", "authority_claim"),
    (r"another agent (already )?(approved|told me|said)", "fake_social_proof"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), tag) for p, tag in _INJECTION_PATTERNS]


def detect_injection(text: str) -> tuple[bool, list[str]]:
    """Heuristically flag likely prompt-injection / social-engineering attempts.

    Returns (flagged, matched_tags). Used for observability, not blocking.
    """
    tags = sorted({tag for rx, tag in _COMPILED if rx.search(text or "")})
    return bool(tags), tags
