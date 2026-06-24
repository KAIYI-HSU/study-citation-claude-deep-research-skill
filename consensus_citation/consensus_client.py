"""
Consensus retrieval clients.

Two interchangeable implementations behind ``BaseConsensusClient.search``:

  * ``FixtureConsensusClient`` — reads bundled JSON fixtures. The demo default,
    so the whole pipeline runs offline with zero credentials.
  * ``ConsensusClient`` — calls the real Consensus API over HTTPS using only the
    standard library (``urllib``), honoring the environment's proxy + CA bundle.

The real endpoint shape is configurable because Consensus access is private:
set ``CONSENSUS_API_BASE_URL`` / ``CONSENSUS_API_KEY`` (or pass them in) and, if
your tenant nests results, ``results_path`` (e.g. ``"results"`` / ``"papers"``).
Every client returns a ``list[dict]`` of raw Consensus result objects with the
fields documented in ``normalize.py``.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = 'https://api.consensus.app/v1/search'


class BaseConsensusClient:
    def search(self, query: str) -> list[dict]:  # pragma: no cover - interface
        raise NotImplementedError


class FixtureConsensusClient(BaseConsensusClient):
    """Return Consensus-shaped results from a bundled JSON file.

    The fixture may be either a bare ``[ ... ]`` list of result objects or an
    object with a ``results`` key.
    """

    def __init__(self, fixture_path: str):
        self.fixture_path = fixture_path

    def search(self, query: str) -> list[dict]:
        with open(self.fixture_path, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data.get('results') or data.get('papers') or []
        return data


class ConsensusClient(BaseConsensusClient):
    """Best-effort real Consensus API client (standard library only)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        results_path: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or os.environ.get('CONSENSUS_API_KEY')
        self.base_url = base_url or os.environ.get('CONSENSUS_API_BASE_URL', DEFAULT_BASE_URL)
        # JSON key under which results are nested in the response, if any.
        self.results_path = results_path or os.environ.get('CONSENSUS_RESULTS_PATH')
        self.timeout = timeout
        if not self.api_key:
            raise ValueError('CONSENSUS_API_KEY is required for the live ConsensusClient')

    def search(self, query: str) -> list[dict]:
        url = f'{self.base_url}?{urllib.parse.urlencode({"query": query})}'
        req = urllib.request.Request(url, method='GET')
        req.add_header('Authorization', f'Bearer {self.api_key}')
        req.add_header('X-API-Key', self.api_key)
        req.add_header('Accept', 'application/json')
        # create_default_context() honors SSL_CERT_FILE / SSL_CERT_DIR; urllib
        # picks up HTTPS_PROXY from the environment automatically.
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        return self._extract_results(payload)

    def _extract_results(self, payload) -> list[dict]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if self.results_path and self.results_path in payload:
                return payload[self.results_path] or []
            for key in ('results', 'papers', 'data', 'hits'):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []
