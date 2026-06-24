"""
Identity & persistence primitives for the Consensus citation mechanism.

This is a SELF-CONTAINED mirror of the proven helpers in the repo's
``scripts/citation_manager.py`` and ``scripts/evidence_store.py``. The hashing
and JSONL logic is copied verbatim so source/evidence identities stay
compatible in spirit with the parent skill, while the new academic helpers
(``normalize_doi``, ``title_year_key``, ``consensus_canonical_locator``) handle
Consensus-API results that arrive as structured fields rather than raw URLs.

Core ideas preserved from the parent mechanism:
  * source_id   = sha256(canonical_locator)[:16]      (content-addressable)
  * evidence_id = sha256(source_id + quote + locator)[:16]
  * all state is append-only JSONL; display numbers are render-time only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import urlparse, urlunparse


# ---------------------------------------------------------------------------
# Canonical locator normalization (mirrors scripts/citation_manager.py)
# ---------------------------------------------------------------------------

# Strict matcher for URLs/identifiers (verbatim from parent skill): a DOI is
# only recognized when carried by a doi.org URL or a ``doi:`` prefix.
DOI_RE = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|doi:)(10\.\d{4,}/\S+)', re.IGNORECASE)
# Lenient matcher for the Consensus ``doi`` field, which is usually a bare DOI
# (``10.1056/NEJMoa1615664``) but may arrive with a prefix.
BARE_DOI_RE = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,}/\S+)', re.IGNORECASE)
ARXIV_RE = re.compile(r'(?:https?://arxiv\.org/abs/|arxiv:)(\d{4}\.\d{4,}(?:v\d+)?)', re.IGNORECASE)

# URL query params that are tracking noise, not content identifiers
TRACKING_PARAMS = frozenset([
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'ref', 'source', 'fbclid', 'gclid', 'mc_cid', 'mc_eid',
])

_WHITESPACE_RE = re.compile(r'\s+')
_PUNCT_RE = re.compile(r'[^\w\s]')


def canonicalize_locator(raw_url: str) -> str:
    """Derive a canonical locator from a raw URL or identifier string.

    Priority: DOI > arXiv > normalized URL. Copied from the parent skill so a
    Consensus result that only carries a URL still normalizes identically.
    """
    m = DOI_RE.search(raw_url)
    if m:
        return f'doi:{m.group(1).rstrip(".")}'

    m = ARXIV_RE.search(raw_url)
    if m:
        return f'arxiv:{m.group(1)}'

    parsed = urlparse(raw_url)
    scheme = (parsed.scheme or 'https').lower()
    host = (parsed.hostname or '').lower()
    path = parsed.path.rstrip('/')
    if parsed.query:
        pairs = []
        for part in parsed.query.split('&'):
            kv = part.split('=', 1)
            if kv[0].lower() not in TRACKING_PARAMS:
                pairs.append(part)
        query = '&'.join(sorted(pairs))
    else:
        query = ''
    return urlunparse((scheme, host, path, '', query, ''))


def normalize_doi(raw_doi: str | None) -> str | None:
    """Extract a bare DOI (``10.xxxx/...``) from any DOI-ish string.

    Accepts ``https://doi.org/10...``, ``doi:10...`` or a bare ``10...`` and
    strips trailing punctuation. Returns None when no valid DOI is present.
    """
    if not raw_doi:
        return None
    m = BARE_DOI_RE.search(raw_doi.strip())
    if not m:
        return None
    return m.group(1).rstrip('.').rstrip()


def title_year_key(title: str, year) -> str:
    """Stable slug from title + year for DOI-less papers.

    lowercase, drop punctuation, collapse whitespace of ``"{title}|{year}"``.
    """
    base = f'{(title or "").strip()}|{year if year not in (None, "") else "unknown"}'
    base = _PUNCT_RE.sub(' ', base.lower())
    return _WHITESPACE_RE.sub(' ', base).strip().replace(' ', '-')


def consensus_canonical_locator(doi: str | None, title: str, year) -> str:
    """Canonical locator for a Consensus result.

    DOI present  -> ``doi:10.xxxx/...``  (cross-query dedup for free)
    DOI missing  -> ``consensus:title:<slug>``  (stable synthetic locator)
    """
    norm = normalize_doi(doi)
    if norm:
        return f'doi:{norm}'
    return f'consensus:title:{title_year_key(title, year)}'


def compute_source_id(canonical_locator: str) -> str:
    """sha256(canonical_locator)[:16] hex (verbatim from parent skill)."""
    return hashlib.sha256(canonical_locator.encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Evidence identity (mirrors scripts/evidence_store.py)
# ---------------------------------------------------------------------------

def normalize_quote(quote: str) -> str:
    """Normalize whitespace for stable hashing (verbatim from parent skill)."""
    return _WHITESPACE_RE.sub(' ', (quote or '').strip()).lower()


def compute_evidence_id(source_id: str, quote: str, locator: str | None) -> str:
    """sha256(source_id + normalized_quote + locator)[:16] (verbatim)."""
    payload = source_id + normalize_quote(quote) + (locator or '')
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Append-only JSONL helpers (verbatim from parent skill)
# ---------------------------------------------------------------------------

def append_jsonl(path: str, obj: dict) -> None:
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def read_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
