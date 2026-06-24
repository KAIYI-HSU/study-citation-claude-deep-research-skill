#!/usr/bin/env python3
"""
End-to-end demo: query -> Consensus retrieval -> citation management ->
LLM synthesis (with in-text [N] citations) -> integrity check -> bibliography.

Examples
--------
Offline (no credentials; bundled fixtures + deterministic synthesis)::

    python consensus_citation/demo.py \\
        --query "Do statins reduce cardiovascular mortality?" \\
        --fixture consensus_citation/fixtures/query_statins.json --strict

Live (real Consensus + real Claude)::

    export CONSENSUS_API_KEY=... ANTHROPIC_API_KEY=...
    python consensus_citation/demo.py --query "Do statins reduce cardiovascular mortality?"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

# Allow running as `python consensus_citation/demo.py` (script) or `-m`.
if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from consensus_citation.consensus_client import ConsensusClient, FixtureConsensusClient
    from consensus_citation.store import CitationStore
    from consensus_citation.synthesize import synthesize
    from consensus_citation.verify import check_citation_integrity
else:
    from .consensus_client import ConsensusClient, FixtureConsensusClient
    from .store import CitationStore
    from .synthesize import synthesize
    from .verify import check_citation_integrity

DEFAULT_FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'query_statins.json')


def _select_client(fixture: str | None):
    """Fixture client when a fixture is given or no live key; else live API."""
    if fixture:
        return FixtureConsensusClient(fixture), f'fixtures ({os.path.basename(fixture)})'
    if os.environ.get('CONSENSUS_API_KEY'):
        return ConsensusClient(), 'live Consensus API'
    return FixtureConsensusClient(DEFAULT_FIXTURE), f'fixtures ({os.path.basename(DEFAULT_FIXTURE)})'


def run_pipeline(
    query: str,
    fixture: str | None = None,
    run_dir: str | None = None,
    strict: bool = False,
    force_offline: bool = False,
) -> dict:
    """Run the full pipeline. Returns a result dict (also suitable for tests)."""
    client, source_label = _select_client(fixture)
    results = client.search(query)

    run_dir = run_dir or tempfile.mkdtemp(prefix='consensus_run_')
    store = CitationStore(run_dir)
    ingest_summary = store.ingest_consensus_results(results, query)

    syn = synthesize(query, store, force_offline=force_offline)
    answer = syn['answer']

    nums = store.display_numbers()
    report = check_citation_integrity(answer, set(nums.values()))
    bibliography = store.bibliography_markdown()

    return {
        'query': query,
        'source_label': source_label,
        'run_dir': run_dir,
        'ingest': ingest_summary,
        'mode': syn['mode'],
        'fallback_reason': syn.get('fallback_reason'),
        'answer': answer,
        'bibliography': bibliography,
        'integrity': report,
        'display_numbers': nums,
    }


def _print_human(result: dict) -> None:
    print(result['answer'])
    print()
    print(result['bibliography'])

    rep = result['integrity']
    print('\n' + '-' * 60, file=sys.stderr)
    print(f'retrieval source : {result["source_label"]}', file=sys.stderr)
    print(f'synthesis mode   : {result["mode"]}', file=sys.stderr)
    if result.get('fallback_reason'):
        print(f'fallback reason  : {result["fallback_reason"]}', file=sys.stderr)
    ing = result['ingest']
    print(
        f'sources          : {ing["unique_sources"]} unique '
        f'({ing["new_sources"]} new, {ing["duplicate_sources"]} duplicate), '
        f'{ing["new_evidence"]} evidence rows',
        file=sys.stderr,
    )
    print(f'run dir          : {result["run_dir"]}', file=sys.stderr)
    print(
        f'citation check   : ok={rep["ok"]} cited={rep["cited"]} '
        f'hallucinated={rep["hallucinated"]} unused={rep["unused"]}',
        file=sys.stderr,
    )
    if rep['uncited_claim_warnings']:
        print(f'  uncited-claim warnings: {len(rep["uncited_claim_warnings"])}', file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Consensus citation demo')
    parser.add_argument('--query', required=True, help='Research question')
    parser.add_argument('--fixture', default=None, help='Path to a Consensus results JSON fixture')
    parser.add_argument('--run-dir', default=None, help='Where to write sources/evidence JSONL')
    parser.add_argument('--offline', action='store_true', help='Force the deterministic offline synthesizer')
    parser.add_argument('--strict', action='store_true', help='Exit non-zero if any citation is hallucinated')
    parser.add_argument('--json', action='store_true', help='Emit the full result as JSON')
    args = parser.parse_args(argv)

    result = run_pipeline(
        query=args.query,
        fixture=args.fixture,
        run_dir=args.run_dir,
        strict=args.strict,
        force_offline=args.offline,
    )

    if args.json:
        printable = dict(result)
        printable['bibliography_json'] = CitationStore(result['run_dir']).bibliography_json()
        print(json.dumps(printable, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    if args.strict and not result['integrity']['ok']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
