#!/usr/bin/env python3
"""
Tests for the independent Consensus citation mechanism.

Conventions mirror the parent skill's tests/ (unittest + tempfile + fixtures).
Run from the repo root:  python -m unittest consensus_citation.tests.test_pipeline
or directly:             python consensus_citation/tests/test_pipeline.py
"""

import os
import sys
import tempfile
import unittest

# Make the package importable when run as a bare script.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from consensus_citation.demo import run_pipeline
from consensus_citation.normalize import normalize_result
from consensus_citation.store import CitationStore, format_authors
from consensus_citation.verify import check_citation_integrity, parse_markers

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fixtures')
STATINS = os.path.join(FIXTURES, 'query_statins.json')
DUPLICATE = os.path.join(FIXTURES, 'query_duplicate.json')


class TestNormalize(unittest.TestCase):
    def test_doi_result_mapping(self):
        result = {
            'title': 'A trial',
            'abstract': 'Abstract text.',
            'authors': ['Smith, J.', 'Lee, K.'],
            'doi': '10.1056/NEJMoa0807646',
            'journal_name': 'NEJM',
            'publish_year': 2008,
            'citation_count': 100,
            'publisher': 'MMS',
            'takeaway': 'a key finding',
        }
        source, evidence = normalize_result(result, 'q', registered_at='2026-01-01T00:00:00Z')
        self.assertTrue(source['canonical_locator'].startswith('doi:'))
        self.assertEqual(source['source_type'], 'academic')
        self.assertEqual(source['metadata_status'], 'doi_verified')
        self.assertEqual(source['journal_name'], 'NEJM')
        self.assertEqual(source['citation_count'], 100)
        self.assertIn('credibility', source)
        types = {(e['evidence_type'], e['locator']) for e in evidence}
        self.assertEqual(types, {('paraphrase', 'takeaway'), ('direct_quote', 'abstract')})

    def test_doi_prefix_insensitive(self):
        a, _ = normalize_result({'title': 'T', 'doi': '10.1/x'}, 'q')
        b, _ = normalize_result({'title': 'T', 'doi': 'https://doi.org/10.1/x'}, 'q')
        self.assertEqual(a['source_id'], b['source_id'])

    def test_synthetic_locator_stable(self):
        r = {'title': 'No DOI Paper', 'publish_year': 2019, 'abstract': 'x'}
        s1, _ = normalize_result(r, 'q')
        s2, _ = normalize_result(r, 'q')
        self.assertTrue(s1['canonical_locator'].startswith('consensus:title:'))
        self.assertEqual(s1['source_id'], s2['source_id'])
        self.assertEqual(s1['metadata_status'], 'title_matched')

    def test_missing_takeaway_and_citation_count(self):
        r = {'title': 'Only abstract', 'abstract': 'just an abstract', 'doi': '10.2/y'}
        source, evidence = normalize_result(r, 'q')
        self.assertIsNone(source['citation_count'])
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['locator'], 'abstract')

    def test_format_authors(self):
        self.assertEqual(format_authors(None), 'Anonymous')
        self.assertEqual(format_authors(['A']), 'A')
        self.assertEqual(format_authors(['A', 'B']), 'A & B')
        self.assertEqual(format_authors(['A', 'B', 'C']), 'A et al.')


class TestStore(unittest.TestCase):
    def _store(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        return CitationStore(self._tmp.name)

    def test_ingest_statins_counts(self):
        import json
        store = self._store()
        with open(STATINS, encoding='utf-8') as f:
            results = json.load(f)['results']
        summary = store.ingest_consensus_results(results, 'do statins reduce mortality')
        self.assertEqual(summary['unique_sources'], 5)
        # 4 results have takeaway+abstract, 1 has abstract only -> 9 evidence rows.
        self.assertEqual(summary['new_evidence'], 9)

    def test_cross_query_dedup(self):
        import json
        store = self._store()
        with open(STATINS, encoding='utf-8') as f:
            r1 = json.load(f)['results']
        with open(DUPLICATE, encoding='utf-8') as f:
            r2 = json.load(f)['results']
        store.ingest_consensus_results(r1, 'q1')
        summary = store.ingest_consensus_results(r2, 'q2')
        # 5 from statins + 2 new from duplicate (CTT shared) = 7 unique.
        self.assertEqual(summary['unique_sources'], 7)
        self.assertEqual(summary['duplicate_sources'], 1)
        # The shared CTT paper appears exactly once in the numbering.
        titles = [s['title'] for s in store.unique_sources()]
        ctt = [t for t in titles if t.startswith('Efficacy and safety of more intensive')]
        self.assertEqual(len(ctt), 1)

    def test_bibliography_matches_numbers(self):
        import json
        store = self._store()
        with open(STATINS, encoding='utf-8') as f:
            results = json.load(f)['results']
        store.ingest_consensus_results(results, 'q')
        nums = set(store.display_numbers().values())
        bib = store.bibliography_markdown()
        for n in nums:
            self.assertIn(f'[{n}]', bib)
        # The result with no citation_count must omit "Cited by".
        self.assertIn('Adverse effects', bib)


class TestVerify(unittest.TestCase):
    def test_parse_markers(self):
        self.assertEqual(parse_markers('a [1]. b [2, 3] c [4,5].'), [1, 2, 3, 4, 5])

    def test_hallucination_detected(self):
        rep = check_citation_integrity('claim [99].', {1, 2, 3})
        self.assertFalse(rep['ok'])
        self.assertIn(99, rep['hallucinated'])

    def test_clean_answer_ok(self):
        rep = check_citation_integrity('A [1]. B [2].', {1, 2, 3})
        self.assertTrue(rep['ok'])
        self.assertEqual(rep['unused'], [3])


class TestPipelineOffline(unittest.TestCase):
    def test_end_to_end_offline_invariant(self):
        with tempfile.TemporaryDirectory() as run_dir:
            result = run_pipeline(
                query='Do statins reduce cardiovascular mortality?',
                fixture=STATINS,
                run_dir=run_dir,
                force_offline=True,
            )
        self.assertEqual(result['mode'], 'offline')
        valid = set(result['display_numbers'].values())
        cited = set(parse_markers(result['answer']))
        # Every in-text marker maps to a real registered source.
        self.assertTrue(cited.issubset(valid))
        self.assertTrue(result['integrity']['ok'])
        self.assertEqual(result['integrity']['hallucinated'], [])
        # Offline synthesizer cites every source -> nothing unused.
        self.assertEqual(cited, valid)
        self.assertIn('## Bibliography', result['bibliography'])


@unittest.skipUnless(os.getenv('ANTHROPIC_API_KEY'), 'no ANTHROPIC_API_KEY; skipping live LLM test')
class TestPipelineLive(unittest.TestCase):
    def test_live_synthesis_passes_integrity(self):
        with tempfile.TemporaryDirectory() as run_dir:
            result = run_pipeline(
                query='Do statins reduce cardiovascular mortality?',
                fixture=STATINS,
                run_dir=run_dir,
            )
        self.assertTrue(result['answer'])
        self.assertTrue(result['integrity']['ok'], result['integrity'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
