"""Tests for skills/opensearch-skills/scripts/opensearch_ops.py

Cluster-free: the OpenSearch bulk call and record loading are mocked so the
provenance-recording wiring in ``cmd_index_bulk`` can be tested in isolation.
"""

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import opensearch_ops
from lib import ingest


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Run each test in an isolated cwd so .opensearch artifacts don't leak."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _args(**kw):
    return types.SimpleNamespace(**kw)


def _fake_records(_path, limit=None):
    # (records, error) shape returned by _load_records_from_file
    return ([{"text": "a"}, {"text": "b"}], None)


def test_index_bulk_records_provenance_for_chunk_set(workdir):
    # A source file under .opensearch/chunks/<name>/ -> provenance recorded
    # mapping the (differently named) cluster index back to the chunk set.
    chunks_dir = ingest.chunks_dir_for("docs")
    chunks_dir.mkdir(parents=True, exist_ok=True)
    src = chunks_dir / "doc.jsonl"
    src.write_text('{"text": "a"}\n')

    args = _args(source_file=str(src), index="docs-v1", count=10)
    with patch("lib.samples._load_records_from_file", _fake_records), \
         patch("lib.operations.index_bulk", return_value='{"indexed_count": 2}'):
        opensearch_ops.cmd_index_bulk(args)

    assert ingest.read_index_provenance() == {"docs-v1": "docs"}


def test_index_bulk_no_provenance_for_non_chunk_source(workdir):
    # A source file NOT under .opensearch/chunks/ -> no provenance recorded.
    other = workdir / "data" / "records.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text('{"text": "a"}\n')

    args = _args(source_file=str(other), index="my-index", count=10)
    with patch("lib.samples._load_records_from_file", _fake_records), \
         patch("lib.operations.index_bulk", return_value='{"indexed_count": 2}'):
        opensearch_ops.cmd_index_bulk(args)

    assert ingest.read_index_provenance() == {}


def test_index_bulk_missing_source_is_noop(workdir):
    args = _args(source_file="", index="my-index", count=10)
    with patch("lib.operations.index_bulk") as bulk:
        opensearch_ops.cmd_index_bulk(args)
        bulk.assert_not_called()
    assert ingest.read_index_provenance() == {}


# ---------------------------------------------------------------------------
# cmd_ingest truncation guard (--confirm flag)
# ---------------------------------------------------------------------------

def test_cmd_ingest_rejects_without_confirm_when_truncated(workdir, capsys):
    """When document exceeds --max-pages and --confirm is not set, cmd_ingest rejects."""
    pdf = workdir / "big.pdf"
    pdf.write_bytes(b"x" * (200 * 1024))  # ~4 pages at 50KB/page estimate

    args = _args(
        source=str(pdf), index=None, max_pages=2, max_tokens=None,
        profile="semantic", background=False, confirm=False,
    )
    # estimate_pages will return >2 for this file size
    with patch("lib.ingest.estimate_pages", return_value=15):
        opensearch_ops.cmd_ingest(args)

    captured = capsys.readouterr()
    import json
    output = json.loads(captured.out)
    assert output["error"] == "truncation_not_confirmed"
    assert output["total_pages"] == 15
    assert output["max_pages"] == 2


def test_cmd_ingest_proceeds_with_confirm(workdir, capsys):
    """When --confirm is set, cmd_ingest proceeds even with truncation."""
    pdf = workdir / "big.pdf"
    pdf.write_bytes(b"x" * (200 * 1024))

    args = _args(
        source=str(pdf), index="test-idx", max_pages=2, max_tokens=None,
        profile="semantic", background=False, confirm=True,
    )
    with patch("lib.ingest.estimate_pages", return_value=15), \
         patch("lib.ingest.ingest_local", return_value={"status": "chunks_ready", "index": "test-idx"}) as mock_ingest:
        opensearch_ops.cmd_ingest(args)
        mock_ingest.assert_called_once()



# ---------------------------------------------------------------------------
# CLI argparse validation — ensure documented flags are accepted
# ---------------------------------------------------------------------------

def _parse_cli_args(argv):
    """Parse CLI args without executing the command. Returns parsed Namespace."""
    import argparse
    from unittest.mock import patch as _p
    with _p("sys.argv", ["opensearch_ops.py"] + argv):
        # Build the parser the same way main() does, but don't dispatch
        import importlib
        import io
        from contextlib import redirect_stderr, redirect_stdout

        # Re-import to get a fresh parser — but main() both parses and dispatches.
        # Instead, just verify parse_known_args doesn't reject the flags.
        # We'll test by catching the SystemExit from argparse on bad flags.
        pass

    # Simpler approach: call main() with the command, mock the dispatch function
    return argv


def test_cli_create_index_accepts_name_flag(monkeypatch):
    """create-index uses --name (not --index)."""
    monkeypatch.setattr("sys.argv", ["opensearch_ops.py", "create-index", "--name", "test-idx", "--body", "{}"])
    with patch("lib.operations.create_index", return_value="Index 'test-idx' created."):
        opensearch_ops.main()


def test_cli_create_index_rejects_index_flag(monkeypatch):
    """create-index does NOT accept --index (it uses --name)."""
    monkeypatch.setattr("sys.argv", ["opensearch_ops.py", "create-index", "--index", "test-idx"])
    with pytest.raises(SystemExit):
        opensearch_ops.main()
