"""
Citation-integrity verification.

Offline, deterministic check that the in-text [N] markers in a synthesized
answer all correspond to real registered sources. Mirrors the intent of the
parent skill's ``scripts/verify_citations.py`` but operates on display-number
markers (no DOI resolution), so it needs no network and always runs.
"""

from __future__ import annotations

import re

# Matches [1], [1, 2], [3,4,5] — a bracket group of comma-separated integers.
MARKER_RE = re.compile(r'\[(\d+(?:\s*,\s*\d+)*)\]')

# Sentence-ish splitter for the soft uncited-claim heuristic.
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')
# A claim "looks factual" if it contains a number, percentage, or 4-digit year.
_FACTUAL_RE = re.compile(r'\d')


def parse_markers(text: str) -> list[int]:
    """Return all cited numbers (with duplicates) in document order."""
    nums: list[int] = []
    for group in MARKER_RE.findall(text):
        for part in group.split(','):
            part = part.strip()
            if part.isdigit():
                nums.append(int(part))
    return nums


def check_citation_integrity(answer_text: str, valid_numbers) -> dict:
    """Verify [N] markers against the set of registered display numbers.

    Returns ``{ok, cited, hallucinated, unused, uncited_claim_warnings}``.
    ``ok`` is False iff any cited number is not a registered source.
    """
    valid = set(valid_numbers)
    cited_list = parse_markers(answer_text)
    cited = set(cited_list)

    hallucinated = sorted(cited - valid)
    unused = sorted(valid - cited)

    warnings: list[str] = []
    for sentence in _SENTENCE_RE.split(answer_text.strip()):
        s = sentence.strip()
        if not s:
            continue
        if _FACTUAL_RE.search(s) and not MARKER_RE.search(s):
            snippet = s if len(s) <= 160 else s[:157] + '…'
            warnings.append(snippet)

    return {
        'ok': not hallucinated,
        'cited': sorted(cited),
        'hallucinated': hallucinated,
        'unused': unused,
        'uncited_claim_warnings': warnings,
    }
