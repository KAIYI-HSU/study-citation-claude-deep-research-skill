"""
consensus_citation — an independent citation mechanism for Consensus API results.

Mirrors the proven patterns of the parent deep-research skill (content-addressable
source IDs, render-time display numbers, evidence-first persistence, in-text [N]
citations with a deterministically generated bibliography) while being fully
self-contained and tuned to academic Consensus fields (journal, publisher,
citation_count, takeaway).

Public API
----------
    normalize_result(result, query)        -> (source, [evidence])
    CitationStore(run_dir)                  -> register/dedup/number/render
    synthesize(query, store)               -> {answer, mode}  (LLM or offline)
    check_citation_integrity(answer, nums) -> integrity report
    run_pipeline(query, ...)               -> full end-to-end result
"""

from .consensus_client import BaseConsensusClient, ConsensusClient, FixtureConsensusClient
from .credibility import academic_credibility
from .normalize import normalize_result
from .store import CitationStore, format_authors
from .synthesize import offline_answer, synthesize, synthesize_answer
from .verify import check_citation_integrity, parse_markers

__all__ = [
    'BaseConsensusClient',
    'ConsensusClient',
    'FixtureConsensusClient',
    'academic_credibility',
    'normalize_result',
    'CitationStore',
    'format_authors',
    'synthesize',
    'synthesize_answer',
    'offline_answer',
    'check_citation_integrity',
    'parse_markers',
    'run_pipeline',
]


def run_pipeline(*args, **kwargs):
    """Lazy proxy to ``demo.run_pipeline`` (avoids importing argparse eagerly)."""
    from .demo import run_pipeline as _run_pipeline
    return _run_pipeline(*args, **kwargs)
