"""Tests for skills/opensearch-skills/scripts/lib/quality.py (agent-judge flow).

Dependency-free: builds the judge payload from local chunk files and round-trips a
verdict to/from _quality.json. No Docling, no cluster, no LLM.
"""

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.quality import (
    build_eval_payload,
    read_verdict,
    save_verdict,
    validate_verdict,
)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make_index(workdir, index="idx", profile="tables", n=5):
    d = workdir / ".opensearch" / "chunks" / index
    d.mkdir(parents=True)
    with (d / "doc.jsonl").open("w") as f:
        for i in range(n):
            rec = {"text": "x" * 400, "chunk_id": i, "page_number": 1, "headings": ["H"]}
            if i == 2:
                rec["has_tables"] = True
            f.write(json.dumps(rec) + "\n")
    (d / "_metadata.json").write_text(json.dumps({
        "source_path": "/tmp/doc.pdf", "profile": profile, "pages_processed": 2,
    }))
    return index


def test_build_eval_payload_missing_index(workdir):
    p = build_eval_payload("nope")
    assert "error" in p


def test_build_eval_payload_shape(workdir):
    idx = _make_index(workdir, profile="tables")
    p = build_eval_payload(idx, max_samples=3)
    assert p["profile"] == "tables"
    assert p["metrics"]["chunk_count"] == 5
    assert isinstance(p["judge_dimensions"], list) and p["judge_dimensions"]
    assert len(p["chunk_sample"]) <= 3
    # the table chunk should be represented in the sample
    assert any(c.get("has_tables") for c in p["chunk_sample"])
    assert "instructions" in p


def test_validate_verdict_rules():
    ok, _ = validate_verdict({"overall": "good", "dimensions": [{"name": "x", "rating": "good"}], "summary": "s"})
    assert ok
    assert not validate_verdict({})[0]
    assert not validate_verdict({"overall": "bogus", "dimensions": [{"name": "x", "rating": "good"}]})[0]
    assert not validate_verdict({"overall": "good", "dimensions": []})[0]
    assert not validate_verdict({"overall": "good", "dimensions": [{"name": "x", "rating": "meh"}]})[0]


def test_save_and_read_verdict_roundtrip(workdir):
    idx = _make_index(workdir)
    verdict = {
        "overall": "good",
        "dimensions": [{"name": "table_structure", "rating": "good", "note": "tables intact"}],
        "summary": "Tables extracted cleanly.",
        "recommendations": ["Consider larger max-tokens"],
    }
    res = save_verdict(idx, verdict)
    assert res["status"] == "saved"
    back = read_verdict(idx)
    assert back["overall"] == "good"
    assert back["judged_by"] == "agent"
    assert "judged_at" in back


def test_save_verdict_rejects_invalid(workdir):
    idx = _make_index(workdir)
    res = save_verdict(idx, {"overall": "nope", "dimensions": []})
    assert "error" in res
    assert read_verdict(idx) is None


def test_read_verdict_none_when_absent(workdir):
    idx = _make_index(workdir)
    assert read_verdict(idx) is None
