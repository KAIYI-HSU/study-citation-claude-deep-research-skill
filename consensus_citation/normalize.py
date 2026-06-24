"""
Normalize a Consensus API result into internal source + evidence records.

Pure functions, no I/O. A Consensus result is a dict with (some of) these
fields::

    title / paper_title, abstract, authors, doi, journal_name,
    publish_year, citation_count, publisher, takeaway

Mapping summary:
  * canonical_locator: doi:... when a DOI exists, else consensus:title:<slug>
  * source record carries the academic fields (journal_name, publisher,
    citation_count) plus a computed credibility block.
  * up to two evidence rows per source:
       takeaway -> evidence_type "paraphrase" (AI-generated, query-tuned)
       abstract -> evidence_type "direct_quote" (authors' own words)
"""

from __future__ import annotations

from datetime import datetime, timezone

from .credibility import academic_credibility
from .identity import (
    compute_evidence_id,
    compute_source_id,
    consensus_canonical_locator,
    normalize_doi,
)


def _get(result: dict, *keys, default=None):
    """Return the first present, non-empty value among ``keys``."""
    for k in keys:
        if k in result and result[k] not in (None, '', []):
            return result[k]
    return default


def _clean_authors(authors):
    """Coerce the authors field into a list[str] or None."""
    if not authors:
        return None
    if isinstance(authors, str):
        # Accept "Smith, J.; Lee, K." or "Smith; Lee" style strings.
        parts = [p.strip() for p in authors.replace(';', ',').split(',')]
        cleaned = [p for p in parts if p]
        return cleaned or None
    if isinstance(authors, list):
        cleaned = [str(a).strip() for a in authors if str(a).strip()]
        return cleaned or None
    return None


def normalize_result(result: dict, query: str, *, registered_at: str | None = None):
    """Map one Consensus result to ``(source_record, [evidence_records])``.

    ``query`` is recorded as the evidence provenance (retrieval_query).
    ``registered_at`` lets callers pin a deterministic timestamp (tests);
    defaults to now (UTC).
    """
    title = _get(result, 'title', 'paper_title', default='Untitled')
    doi = normalize_doi(_get(result, 'doi'))
    year = _get(result, 'publish_year', 'year')
    year = str(year) if year not in (None, '') else None
    authors = _clean_authors(_get(result, 'authors'))
    journal_name = _get(result, 'journal_name', 'journal')
    publisher = _get(result, 'publisher')
    citation_count = _get(result, 'citation_count')
    try:
        citation_count = int(citation_count) if citation_count is not None else None
    except (TypeError, ValueError):
        citation_count = None

    canonical = consensus_canonical_locator(doi, title, year)
    source_id = compute_source_id(canonical)
    raw_url = f'https://doi.org/{doi}' if doi else ''
    ts = registered_at or datetime.now(timezone.utc).isoformat()

    source = {
        'source_id': source_id,
        'canonical_locator': canonical,
        'doi': doi,
        'raw_url': raw_url,
        'title': title,
        'authors': authors,
        'year': year,
        'source_type': 'academic',
        'journal_name': journal_name,
        'publisher': publisher,
        'citation_count': citation_count,
        'credibility': academic_credibility(citation_count, journal_name, publisher, year),
        'metadata_status': 'doi_verified' if doi else 'title_matched',
        'registered_at': ts,
    }

    evidence: list[dict] = []
    takeaway = _get(result, 'takeaway')
    if takeaway:
        evidence.append(_evidence_row(source_id, takeaway, 'paraphrase', 'takeaway', query, ts))
    abstract = _get(result, 'abstract')
    if abstract:
        evidence.append(_evidence_row(source_id, abstract, 'direct_quote', 'abstract', query, ts))

    return source, evidence


def _evidence_row(source_id, quote, evidence_type, locator, query, ts) -> dict:
    return {
        'evidence_id': compute_evidence_id(source_id, quote, locator),
        'source_id': source_id,
        'retrieval_query': query,
        'locator': locator,
        'quote': quote,
        'evidence_type': evidence_type,
        'captured_at': ts,
    }
