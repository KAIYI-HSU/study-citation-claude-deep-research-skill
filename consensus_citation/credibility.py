"""
Academic credibility scoring for Consensus sources.

Adapts the tiered, weighted 0-100 scoring idea from the parent skill's
``scripts/source_evaluator.py`` (which scores by web-domain authority) to the
academic signals that Consensus provides: citation count, journal/publisher
prestige, and recency. This is informational metadata attached to a source —
it can be surfaced in the bibliography but never gates the pipeline.
"""

from __future__ import annotations

# A small prestige set keyed by case-insensitive substring match on the
# journal name or publisher. Mirrors the spirit of source_evaluator's
# HIGH_AUTHORITY_DOMAINS, expressed for scholarly venues.
HIGH_PRESTIGE = frozenset([
    'nature', 'science', 'cell', 'lancet', 'new england journal', 'nejm',
    'pnas', 'proceedings of the national academy', 'jama', 'bmj',
    'ieee', 'acm', 'elsevier', 'springer', 'wiley', 'oxford university press',
    'cambridge university press', 'plos',
])


def _impact_score(citation_count) -> float:
    """0-100 from citation count. None -> neutral 50 (unknown, not penalized)."""
    if citation_count is None:
        return 50.0
    try:
        c = int(citation_count)
    except (TypeError, ValueError):
        return 50.0
    if c < 10:
        return 55.0
    if c < 50:
        return 70.0
    if c < 200:
        return 82.0
    return 92.0


def _prestige_score(journal_name, publisher) -> float:
    """0-100 from venue prestige; neutral 60 when unknown."""
    haystack = ' '.join(filter(None, [journal_name, publisher])).lower()
    if not haystack:
        return 55.0
    for needle in HIGH_PRESTIGE:
        if needle in haystack:
            return 90.0
    # A named (but not top-tier) venue is still better than no venue at all.
    return 65.0


def _recency_score(year) -> float:
    """0-100 from publish year; neutral 60 when unknown.

    Recent work scores higher, but old foundational work is not heavily
    penalized (floors at 50). Uses a fixed reference year to stay deterministic
    and dependency-free.
    """
    REFERENCE_YEAR = 2026
    if year in (None, ''):
        return 60.0
    try:
        y = int(str(year)[:4])
    except (TypeError, ValueError):
        return 60.0
    age = REFERENCE_YEAR - y
    if age <= 2:
        return 95.0
    if age <= 5:
        return 85.0
    if age <= 10:
        return 72.0
    if age <= 20:
        return 60.0
    return 50.0


def academic_credibility(citation_count, journal_name, publisher, year) -> dict:
    """Combine impact, prestige and recency into a 0-100 score + recommendation.

    Returns a dict: ``{score, tier, recommendation, factors}``.
    """
    impact = _impact_score(citation_count)
    prestige = _prestige_score(journal_name, publisher)
    recency = _recency_score(year)
    overall = round(0.5 * impact + 0.3 * prestige + 0.2 * recency, 1)

    if overall >= 80:
        tier, rec = 'high', 'high_trust'
    elif overall >= 60:
        tier, rec = 'moderate', 'moderate_trust'
    elif overall >= 40:
        tier, rec = 'low', 'low_trust'
    else:
        tier, rec = 'minimal', 'verify'

    return {
        'score': overall,
        'tier': tier,
        'recommendation': rec,
        'factors': {
            'impact': impact,
            'prestige': prestige,
            'recency': recency,
        },
    }
