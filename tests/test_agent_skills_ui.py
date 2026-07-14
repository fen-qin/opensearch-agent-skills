"""Tests for skills/opensearch-skills/scripts/lib/ui.py

Cluster-free: exercises the pure helper that gates the ingestion tab.
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.ui import _has_local_chunks
from lib import ingest


def test_has_local_chunks_empty_index_name():
    assert _has_local_chunks("") is False
    assert _has_local_chunks(None) is False


def test_has_local_chunks_missing_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _has_local_chunks("no-such-index") is False


def test_has_local_chunks_dir_without_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / ".opensearch" / "chunks" / "my-index"
    d.mkdir(parents=True)
    # metadata but no chunk files -> not ingestible
    (d / "_metadata.json").write_text("{}")
    assert _has_local_chunks("my-index") is False


def test_has_local_chunks_with_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / ".opensearch" / "chunks" / "my-index"
    d.mkdir(parents=True)
    (d / "part-0.jsonl").write_text('{"text": "hello"}\n')
    assert _has_local_chunks("my-index") is True


# ---------------------------------------------------------------------------
# Ingestion-tab decision (what /api/config computes): show_ingestion_tab and
# ingestion_chunk_index both derive from resolve_chunk_source. These assert the
# decision the handler makes, independent of the HTTP layer.
# ---------------------------------------------------------------------------

def _chunk_source_decision(index_name):
    """Mirror the handler's local-endpoint decision: chunk_source drives both
    show_ingestion_tab (bool) and ingestion_chunk_index (str)."""
    chunk_source = ingest.resolve_chunk_source(index_name)
    return {"show_ingestion_tab": bool(chunk_source), "ingestion_chunk_index": chunk_source}


def _make_chunks(name):
    d = Path(".opensearch") / "chunks" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "doc.jsonl").write_text('{"text": "hi"}\n')


def test_decision_structured_index_search_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _chunk_source_decision("ecommerce") == {
        "show_ingestion_tab": False, "ingestion_chunk_index": ""
    }


def test_decision_same_name_chunks_shows_tab(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_chunks("docs")
    assert _chunk_source_decision("docs") == {
        "show_ingestion_tab": True, "ingestion_chunk_index": "docs"
    }


def test_decision_versioned_index_via_provenance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_chunks("docs")
    ingest.record_index_provenance("docs-v1", "docs")
    assert _chunk_source_decision("docs-v1") == {
        "show_ingestion_tab": True, "ingestion_chunk_index": "docs"
    }


def test_fallback_matches_primary_for_same_name(tmp_path, monkeypatch):
    # _has_local_chunks is the handler's fallback when resolve_chunk_source is
    # unavailable; for the same-name case the two must agree.
    monkeypatch.chdir(tmp_path)
    _make_chunks("docs")
    assert _has_local_chunks("docs") is True
    assert bool(ingest.resolve_chunk_source("docs")) is True
    assert _has_local_chunks("ecommerce") is False
    assert bool(ingest.resolve_chunk_source("ecommerce")) is False


# ---------------------------------------------------------------------------
# set_ui_mode
# ---------------------------------------------------------------------------

def test_set_ui_mode_valid_modes():
    from lib.ui import set_ui_mode
    assert set_ui_mode("full") == "UI mode set to 'full'."
    assert set_ui_mode("ingestion") == "UI mode set to 'ingestion'."
    assert set_ui_mode("search") == "UI mode set to 'search'."


def test_set_ui_mode_invalid_falls_back_to_full():
    from lib.ui import set_ui_mode
    assert set_ui_mode("invalid") == "UI mode set to 'full'."
    assert set_ui_mode("") == "UI mode set to 'full'."
