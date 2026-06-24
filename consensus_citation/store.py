"""
CitationStore — registers Consensus sources & evidence, assigns render-time
display numbers, and renders the evidence digest + bibliography.

State is append-only JSONL (``sources.jsonl`` + ``evidence.jsonl``) in a run
directory, mirroring the parent skill. Display numbers ``[1][2][3]`` are
assigned at render time from registration order and are never stored — so the
same numbers feed the LLM prompt and the generated bibliography, guaranteeing
in-text ``[N]`` markers and reference entries always line up.
"""

from __future__ import annotations

import os

from .identity import append_jsonl, read_jsonl
from .normalize import normalize_result

ABSTRACT_DIGEST_CHARS = 600


def format_authors(authors) -> str:
    """1 -> 'Smith'; 2 -> 'Smith & Lee'; 3+ -> 'Smith et al.'; none -> 'Anonymous'.

    Mirrors the author logic in scripts/citation_manager.py:cmd_export_bibliography.
    """
    if not authors:
        return 'Anonymous'
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f'{authors[0]} & {authors[1]}'
    return f'{authors[0]} et al.'


class CitationStore:
    """Append-only source/evidence registry for one research run."""

    def __init__(self, run_dir: str):
        self.run_dir = os.path.abspath(run_dir)
        os.makedirs(self.run_dir, exist_ok=True)
        self.sources_path = os.path.join(self.run_dir, 'sources.jsonl')
        self.evidence_path = os.path.join(self.run_dir, 'evidence.jsonl')

    # ------------------------------------------------------------------
    # Registration (dedup by content-addressable id)
    # ------------------------------------------------------------------

    def register_source(self, source: dict) -> str:
        """Append a source unless its source_id already exists. Returns status."""
        sid = source['source_id']
        for row in read_jsonl(self.sources_path):
            if row.get('source_id') == sid:
                return 'duplicate'
        append_jsonl(self.sources_path, source)
        return 'registered'

    def add_evidence(self, evidence: dict) -> str:
        """Append an evidence row unless its evidence_id already exists."""
        eid = evidence['evidence_id']
        for row in read_jsonl(self.evidence_path):
            if row.get('evidence_id') == eid:
                return 'duplicate'
        append_jsonl(self.evidence_path, evidence)
        return 'registered'

    def ingest_consensus_results(self, results: list[dict], query: str) -> dict:
        """Normalize + register a batch of Consensus results.

        Returns a small summary dict for logging.
        """
        new_sources = dup_sources = new_evidence = 0
        for result in results:
            source, evidence_rows = normalize_result(result, query)
            if self.register_source(source) == 'registered':
                new_sources += 1
            else:
                dup_sources += 1
            for ev in evidence_rows:
                if self.add_evidence(ev) == 'registered':
                    new_evidence += 1
        return {
            'new_sources': new_sources,
            'duplicate_sources': dup_sources,
            'new_evidence': new_evidence,
            'unique_sources': len(self.unique_sources()),
        }

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def unique_sources(self) -> list[dict]:
        """Sources in registration order, deduped by source_id."""
        seen: set[str] = set()
        unique: list[dict] = []
        for row in read_jsonl(self.sources_path):
            sid = row.get('source_id')
            if sid not in seen:
                seen.add(sid)
                unique.append(row)
        return unique

    def display_numbers(self) -> dict[str, int]:
        """Map source_id -> [N], assigned in registration order (render-time)."""
        return {src['source_id']: i for i, src in enumerate(self.unique_sources(), 1)}

    def _evidence_by_source(self) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        seen: set[str] = set()
        for ev in read_jsonl(self.evidence_path):
            eid = ev.get('evidence_id')
            if eid in seen:
                continue
            seen.add(eid)
            grouped.setdefault(ev['source_id'], []).append(ev)
        return grouped

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def evidence_digest(self) -> str:
        """Numbered evidence block fed to the LLM, in display order."""
        nums = self.display_numbers()
        ev_by_src = self._evidence_by_source()
        blocks: list[str] = []
        for src in self.unique_sources():
            n = nums[src['source_id']]
            authors = format_authors(src.get('authors'))
            year = src.get('year') or 'n.d.'
            journal = src.get('journal_name') or 'unknown venue'
            header = f'[{n}] {src.get("title", "Untitled")} — {authors} ({year}, {journal}).'
            cc = src.get('citation_count')
            if cc is not None:
                header += f' Cited by {cc}.'

            takeaway = abstract = None
            for ev in ev_by_src.get(src['source_id'], []):
                if ev.get('locator') == 'takeaway':
                    takeaway = ev.get('quote')
                elif ev.get('locator') == 'abstract':
                    abstract = ev.get('quote')

            lines = [header]
            if takeaway:
                lines.append(f'    Takeaway: {takeaway}')
            if abstract:
                snippet = abstract.strip()
                if len(snippet) > ABSTRACT_DIGEST_CHARS:
                    snippet = snippet[:ABSTRACT_DIGEST_CHARS].rstrip() + '…'
                lines.append(f'    Abstract: {snippet}')
            if not takeaway and not abstract:
                lines.append('    (no extracted text)')
            blocks.append('\n'.join(lines))
        return '\n\n'.join(blocks)

    def ordered_view(self) -> list[dict]:
        """Display-ordered list of sources with their takeaway/abstract.

        Used by the offline synthesizer to build a deterministic, fully-cited
        answer without an LLM.
        """
        nums = self.display_numbers()
        ev_by_src = self._evidence_by_source()
        view = []
        for src in self.unique_sources():
            takeaway = abstract = None
            for ev in ev_by_src.get(src['source_id'], []):
                if ev.get('locator') == 'takeaway':
                    takeaway = ev.get('quote')
                elif ev.get('locator') == 'abstract':
                    abstract = ev.get('quote')
            view.append({
                'number': nums[src['source_id']],
                'source_id': src['source_id'],
                'title': src.get('title', 'Untitled'),
                'authors': src.get('authors'),
                'year': src.get('year'),
                'takeaway': takeaway,
                'abstract': abstract,
            })
        return view

    def bibliography_markdown(self) -> str:
        """Deterministic bibliography rendered from registered sources."""
        nums = self.display_numbers()
        lines = ['## Bibliography', '']
        for src in self.unique_sources():
            n = nums[src['source_id']]
            authors = format_authors(src.get('authors'))
            year = src.get('year') or 'n.d.'
            title = src.get('title', 'Untitled')
            parts = [f'[{n}] {authors} ({year}). "{title}".']
            if src.get('journal_name'):
                parts.append(f'{src["journal_name"]}.')
            if src.get('publisher'):
                parts.append(f'{src["publisher"]}.')
            cc = src.get('citation_count')
            if cc is not None:
                parts.append(f'Cited by {cc}.')
            cred = src.get('credibility') or {}
            if cred.get('recommendation'):
                parts.append(f'(credibility: {cred["recommendation"]}).')
            if src.get('raw_url'):
                parts.append(src['raw_url'])
            lines.append(' '.join(parts))
        return '\n'.join(lines)

    def bibliography_json(self) -> list[dict]:
        nums = self.display_numbers()
        out = []
        for src in self.unique_sources():
            out.append({
                'display_number': nums[src['source_id']],
                'source_id': src['source_id'],
                'canonical_locator': src['canonical_locator'],
                'doi': src.get('doi'),
                'title': src.get('title', ''),
                'authors': src.get('authors'),
                'year': src.get('year'),
                'journal_name': src.get('journal_name'),
                'publisher': src.get('publisher'),
                'citation_count': src.get('citation_count'),
                'credibility': src.get('credibility'),
                'raw_url': src.get('raw_url', ''),
            })
        return out
