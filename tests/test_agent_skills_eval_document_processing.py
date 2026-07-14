"""Tests for skills/opensearch-skills/scripts/lib/eval_document_processing.py

Dependency-free: exercises metric computation and scorecard rendering on synthetic
chunk records (no Docling, no cluster, no PDFs).
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.eval_document_processing import (
    compute_metrics,
    estimate_tokens,
    render_scorecard,
    sample_chunks,
)


def test_estimate_tokens_basic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1          # 4 chars ~ 1 token
    assert estimate_tokens("a" * 400) == 100


def test_compute_metrics_empty():
    m = compute_metrics([])
    assert m["chunk_count"] == 0
    assert m["avg_tokens"] == 0
    assert m["coverage"] is None


def test_compute_metrics_basic_fields():
    chunks = [
        {"text": "a" * 400, "headings": ["Intro"]},
        {"text": "b" * 200, "headings": []},
        {"text": "c" * 600, "headings": ["Methods"], "has_tables": True},
    ]
    m = compute_metrics(chunks)
    assert m["chunk_count"] == 3
    assert m["max_tokens"] == 150     # 600/4
    assert m["min_tokens"] == 50      # 200/4
    assert m["median_tokens"] == 100  # 400/4
    assert m["pct_chunks_with_headings"] == round(100 * 2 / 3, 1)
    assert m["chunks_with_tables"] == 1
    assert m["total_chars"] == 1200


def test_compute_metrics_coverage_ratio():
    chunks = [{"text": "x" * 500, "headings": []}]
    m = compute_metrics(chunks, source_text_chars=1000)
    assert m["coverage"] == 0.5


def test_compute_metrics_coverage_capped():
    # Table markdown / heading context can inflate chunk chars beyond source.
    chunks = [{"text": "x" * 100000, "headings": []}]
    m = compute_metrics(chunks, source_text_chars=10)
    assert m["coverage"] == 9.99


def test_render_scorecard_facts_only():
    results = [
        {"file": "a.pdf", "profile": "semantic", "processing_seconds": 1.2,
         "metrics": compute_metrics([{"text": "x" * 400, "headings": ["H"]}], 400)},
        {"file": "b.pdf", "profile": "scanned", "error": "OcrError: boom"},
    ]
    md = render_scorecard(results)
    assert "# Document Processing Metrics" in md
    assert "a.pdf" in md and "semantic" in md
    assert "ERROR: OcrError: boom" in md
    # No hard-coded quality score / stars in the facts-only scorecard.
    assert "★" not in md
    assert "LLM-as-judge" in md


# ---------------------------------------------------------------------------
# chunk sampling (material for the agent/LLM judge)
# ---------------------------------------------------------------------------

def test_sample_chunks_empty():
    assert sample_chunks([]) == []


def test_sample_chunks_caps_count_and_text():
    chunks = [{"text": "x" * 2000, "chunk_id": i, "page_number": 1, "headings": []} for i in range(50)]
    s = sample_chunks(chunks, max_samples=8, text_cap=100)
    assert len(s) <= 8
    assert all(len(c["text"]) <= 101 for c in s)  # 100 + ellipsis
    # first and last chunks are represented
    ids = [c["chunk_id"] for c in s]
    assert 0 in ids and 49 in ids


def test_sample_chunks_prefers_effect_chunks():
    chunks = [{"text": "t", "chunk_id": i, "page_number": 1, "headings": []} for i in range(20)]
    chunks[7]["has_tables"] = True
    chunks[13]["has_image_descriptions"] = True
    s = sample_chunks(chunks, max_samples=5)
    ids = [c["chunk_id"] for c in s]
    assert 7 in ids and 13 in ids
