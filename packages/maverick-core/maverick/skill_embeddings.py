"""Embedding-based skill retrieval (optional, falls back to lexical).

The v0.1 skill retriever scored triggers via word overlap + substring
bonus -- works for obvious matches, brittle for paraphrases. This
module adds an embeddings layer when ``fastembed`` is installed:

  1. On first use, embed every installed skill's triggers + first line
     of the body and cache vectors to ``~/.maverick/skill_embeddings.json``.
  2. At retrieval time, embed the incoming goal once, do cosine
     similarity against the cache, and return the top-K.
  3. Cache invalidation: if a skill file's mtime is newer than its
     cached entry, re-embed just that one.

``fastembed`` is intentionally an optional dep -- it pulls in ONNX
runtime (~80MB). Without it, ``relevant_skills`` keeps using the
fast lexical scorer in ``skills.py``. Users opt in via::

    pip install 'maverick[embeddings]'

Design choices:
  - all-MiniLM-L6-v2 (384-dim, ~22MB ONNX) -- small enough for laptops,
    good enough for trigger-vs-goal matching.
  - JSON cache, not SQLite/parquet, so users can inspect/edit.
  - Cosine similarity by hand (numpy if available; pure-Python fallback)
    so we don't drag numpy in as a required dep.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".maverick" / "skill_embeddings.json"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model = None  # lazy singleton


def _have_fastembed() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    """Lazy-load the fastembed TextEmbedding model. Cached for the process."""
    global _model
    if _model is not None:
        return _model
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None
    try:
        _model = TextEmbedding(model_name=MODEL_NAME)
        return _model
    except Exception as e:  # pragma: no cover
        log.error("failed to load embedding model: %s", e)
        return None


def embed(texts: list[str]) -> Optional[list[list[float]]]:
    """Embed a batch of strings. Returns None if embeddings unavailable."""
    model = _get_model()
    if model is None or not texts:
        return None
    try:
        # fastembed returns a generator of numpy arrays.
        return [list(map(float, v)) for v in model.embed(texts)]
    except Exception as e:  # pragma: no cover
        log.error("embedding call failed: %s", e)
        return None


@dataclass
class CachedEmbedding:
    name: str
    text: str          # what we embedded (triggers + first body line)
    mtime: float       # source file mtime when we cached
    vector: list[float]


def _load_cache() -> dict[str, CachedEmbedding]:
    if not CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, CachedEmbedding] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if not all(k in entry for k in ("text", "mtime", "vector")):
            continue
        out[name] = CachedEmbedding(
            name=name,
            text=entry["text"],
            mtime=float(entry["mtime"]),
            vector=entry["vector"],
        )
    return out


def _save_cache(cache: dict[str, CachedEmbedding]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        name: {"text": e.text, "mtime": e.mtime, "vector": e.vector}
        for name, e in cache.items()
    }
    CACHE_PATH.write_text(json.dumps(raw))


def _skill_to_embed_text(skill) -> str:
    """What we feed the embedder for a given skill."""
    triggers = " | ".join(skill.triggers) if skill.triggers else ""
    first_line = (skill.body or "").splitlines()[0] if skill.body else ""
    return f"{skill.name}: {triggers}\n{first_line}".strip()


def build_or_update_cache(skills: list) -> dict[str, CachedEmbedding]:
    """Ensure every skill has an up-to-date cached embedding.

    Returns the cache. Mutates the on-disk cache file.
    """
    cache = _load_cache()
    to_embed: list[tuple[str, str, float]] = []
    for s in skills:
        try:
            mtime = s.path.stat().st_mtime
        except (OSError, AttributeError):
            mtime = 0.0
        cached = cache.get(s.name)
        if cached and cached.mtime >= mtime:
            continue
        to_embed.append((s.name, _skill_to_embed_text(s), mtime))

    if not to_embed:
        return cache

    vectors = embed([t[1] for t in to_embed])
    if vectors is None:
        return cache

    for (name, text, mtime), vec in zip(to_embed, vectors):
        cache[name] = CachedEmbedding(name=name, text=text, mtime=mtime, vector=vec)

    # Drop entries for skills that no longer exist.
    valid_names = {s.name for s in skills}
    cache = {k: v for k, v in cache.items() if k in valid_names}

    _save_cache(cache)
    return cache


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def relevant_skills_embed(
    goal: str, all_skills: list, max_n: int = 3, threshold: float = 0.35,
) -> Optional[list]:
    """Embedding-based skill retrieval. Returns None if embeddings unavailable.

    Caller should fall back to ``maverick.skills.relevant_skills`` (lexical)
    when this returns None.
    """
    if not _have_fastembed():
        return None
    if not all_skills:
        return []

    cache = build_or_update_cache(all_skills)
    if not cache:
        return None

    goal_vecs = embed([goal])
    if not goal_vecs:
        return None
    goal_vec = goal_vecs[0]

    by_name = {s.name: s for s in all_skills}
    scored: list[tuple[float, object]] = []
    for name, entry in cache.items():
        if name not in by_name:
            continue
        score = _cosine(goal_vec, entry.vector)
        if score >= threshold:
            scored.append((score, by_name[name]))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_n]]
