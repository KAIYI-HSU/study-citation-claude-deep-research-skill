"""
LLM synthesis with a deterministic offline fallback.

``synthesize(query, store)`` returns the prose answer (no bibliography — the
caller appends that from the store) plus the mode used. When the ``anthropic``
SDK and ``ANTHROPIC_API_KEY`` are both available it calls Claude
(``claude-opus-4-8``, adaptive thinking, streaming); otherwise — or on any
import/auth/network/TLS error — it falls back to ``offline_answer``, which still
exercises the full ``[N]`` citation + bibliography pipeline so the demo always
runs.
"""

from __future__ import annotations

import os

from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

MODEL = 'claude-opus-4-8'


def llm_available() -> bool:
    """True only if the SDK is importable and an API key is configured."""
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def synthesize_answer(query: str, evidence_digest: str, n: int) -> str:
    """Call Claude to produce a cited answer. Raises on any failure."""
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY; httpx honors HTTPS_PROXY
    user_prompt = USER_PROMPT_TEMPLATE.format(query=query, n=n, evidence_digest=evidence_digest)
    # claude-opus-4-8: adaptive thinking only (enabled/budget_tokens would 400);
    # stream + get_final_message() avoids HTTP timeouts on larger outputs.
    with client.messages.stream(
        model=MODEL,
        max_tokens=8000,
        thinking={'type': 'adaptive'},
        output_config={'effort': 'medium'},
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': user_prompt}],
    ) as stream:
        final = stream.get_final_message()
    return ''.join(b.text for b in final.content if b.type == 'text').strip()


def offline_answer(query: str, ordered_view: list[dict]) -> str:
    """Deterministic, fully-cited answer built from the store (no LLM).

    Every sentence carries a real, in-range [N], so the integrity check passes
    and the citation pipeline is demonstrated end-to-end without any API.
    """
    if not ordered_view:
        return f'No sources were retrieved for: {query}'

    parts = [
        f'Based on {len(ordered_view)} retrieved source(s), here is what the '
        f'literature indicates regarding the question: "{query}".',
        '',
    ]
    for item in ordered_view:
        n = item['number']
        takeaway = item.get('takeaway')
        abstract = item.get('abstract')
        if takeaway:
            # Takeaways are lowercase fragments by design — splice mid-sentence.
            parts.append(f'According to the evidence, {takeaway.strip().rstrip(".")} [{n}].')
        elif abstract:
            # Abstracts are full sentences — use the first one as a standalone claim.
            first = abstract.strip().split('. ')[0].rstrip('.')
            parts.append(f'{first} [{n}].')
        else:
            parts.append(
                f'A relevant source was identified but provided no extractable '
                f'finding for this question [{n}].'
            )
    parts.append('')
    parts.append(
        'Taken together, these sources point in a broadly consistent direction; '
        'this synthesis is inferential and is not asserted by any single source.'
    )
    return '\n'.join(parts)


def synthesize(query: str, store, *, force_offline: bool = False) -> dict:
    """Top-level: pick LLM or offline, return ``{answer, mode}``."""
    digest = store.evidence_digest()
    n = len(store.display_numbers())

    if not force_offline and llm_available():
        try:
            answer = synthesize_answer(query, digest, n)
            if answer:
                return {'answer': answer, 'mode': 'llm'}
        except Exception as exc:  # noqa: BLE001 - any failure -> graceful fallback
            return {
                'answer': offline_answer(query, store.ordered_view()),
                'mode': 'offline',
                'fallback_reason': f'{type(exc).__name__}: {exc}',
            }

    return {'answer': offline_answer(query, store.ordered_view()), 'mode': 'offline'}
