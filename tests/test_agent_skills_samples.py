"""Tests for skills/opensearch-skills/scripts/lib/samples.py"""

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.samples import (
    _load_records_from_file,
    _infer_text_fields,
    _is_restricted_ip,
    _validate_url,
    _build_safe_opener,
    _RevalidatingRedirectHandler,
    _ValidatingHTTPConnection,
    _ValidatingHTTPSConnection,
    load_sample_from_file,
    load_sample_from_paste,
)


# ---------------------------------------------------------------------------
# _infer_text_fields
# ---------------------------------------------------------------------------
def test_infer_text_fields_detects_multiword_strings():
    doc = {
        "id": "1",
        "title": "The quick brown fox jumps",
        "count": 42,
    }
    result = _infer_text_fields(doc)

    assert "title" in result
    assert "id" not in result
    assert "count" not in result


def test_infer_text_fields_ignores_short_strings():
    doc = {"code": "AB", "name": "ok then"}

    result = _infer_text_fields(doc)

    assert "code" not in result


def test_infer_text_fields_empty_doc():
    assert _infer_text_fields({}) == []


def test_infer_text_fields_non_string_values():
    doc = {"count": 100, "flag": True, "tags": ["a", "b"]}

    assert _infer_text_fields(doc) == []


# ---------------------------------------------------------------------------
# _load_records_from_file — JSON
# ---------------------------------------------------------------------------
def test_load_records_json_array(tmp_path):
    f = tmp_path / "data.json"
    f.write_text(json.dumps([{"a": 1}, {"a": 2}, {"a": 3}]))

    records, error = _load_records_from_file(f, limit=2)

    assert error is None
    assert len(records) == 2
    assert records[0]["a"] == 1


def test_load_records_jsonl(tmp_path):
    f = tmp_path / "data.jsonl"
    f.write_text('{"x":1}\n{"x":2}\n{"x":3}\n')

    records, error = _load_records_from_file(f, limit=10)

    assert error is None
    assert len(records) == 3


def test_load_records_json_empty_lines_skipped(tmp_path):
    f = tmp_path / "data.ndjson"
    f.write_text('{"x":1}\n\n{"x":2}\n\n')

    records, error = _load_records_from_file(f, limit=10)

    assert error is None
    assert len(records) == 2


# ---------------------------------------------------------------------------
# _load_records_from_file — CSV/TSV
# ---------------------------------------------------------------------------
def test_load_records_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("id,name,score\n1,Alice,95\n2,Bob,87\n3,Carol,91\n")

    records, error = _load_records_from_file(f, limit=2)

    assert error is None
    assert len(records) == 2
    assert records[0]["name"] == "Alice"


def test_load_records_tsv(tmp_path):
    f = tmp_path / "data.tsv"
    f.write_text("tconst\tprimaryTitle\n" "tt001\tCarmencita\n" "tt002\tClown\n")

    records, error = _load_records_from_file(f, limit=10)

    assert error is None
    assert len(records) == 2
    assert records[0]["tconst"] == "tt001"


# ---------------------------------------------------------------------------
# _load_records_from_file — unsupported
# ---------------------------------------------------------------------------
def test_load_records_unsupported_format(tmp_path):
    f = tmp_path / "data.xml"
    f.write_text("<root/>")

    records, error = _load_records_from_file(f, limit=10)

    assert records == []
    assert "Unsupported file format" in error


# ---------------------------------------------------------------------------
# load_sample_from_file
# ---------------------------------------------------------------------------
def test_load_sample_from_file_success(tmp_path):
    f = tmp_path / "movies.json"
    f.write_text(json.dumps([
        {"title": "The Matrix is a great movie", "year": 1999},
        {"title": "Inception is mind bending", "year": 2010},
    ]))

    result = json.loads(load_sample_from_file(str(f)))

    assert result["status"] == "loaded"
    assert result["record_count"] == 2
    assert result["sample_doc"]["title"] == "The Matrix is a great movie"
    assert "title" in result["text_fields"]
    assert result["text_search_required"] is True


def test_load_sample_from_file_not_found():
    result = json.loads(load_sample_from_file("/nonexistent/path.json"))

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_load_sample_from_file_empty_records(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("[]")

    result = json.loads(load_sample_from_file(str(f)))

    assert "error" in result
    assert "No records" in result["error"]


def test_load_sample_from_file_numeric_only(tmp_path):
    f = tmp_path / "numeric.json"
    f.write_text(json.dumps([{"id": 1, "score": 99.5}]))

    result = json.loads(load_sample_from_file(str(f)))

    assert result["status"] == "loaded"
    assert result["text_fields"] == []
    assert result["text_search_required"] is False


# ---------------------------------------------------------------------------
# load_sample_from_paste
# ---------------------------------------------------------------------------
def test_load_sample_from_paste_valid_json():
    doc = '{"title": "Test document with enough words", "id": 1}'

    result = json.loads(load_sample_from_paste(doc))

    assert result["status"] == "loaded"
    assert result["source"] == "paste"
    assert result["record_count"] == 1
    assert result["sample_doc"]["id"] == 1


def test_load_sample_from_paste_invalid_json():
    result = json.loads(load_sample_from_paste("not json at all"))

    assert "error" in result
    assert "Invalid JSON" in result["error"]


def test_load_sample_from_paste_non_object():
    result = json.loads(load_sample_from_paste("[1, 2, 3]"))

    assert "error" in result
    assert "must be a JSON object" in result["error"]


def test_load_sample_from_paste_text_field_detection():
    doc = json.dumps({
        "title": "A document with several words here",
        "code": "XY",
    })

    result = json.loads(load_sample_from_paste(doc))

    assert "title" in result["text_fields"]
    assert "code" not in result["text_fields"]


# ---------------------------------------------------------------------------
# _validate_url — SSRF prevention
# ---------------------------------------------------------------------------
def test_validate_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="http or https"):
        _validate_url("file:///etc/passwd")


def test_validate_url_rejects_ftp_scheme():
    with pytest.raises(ValueError, match="http or https"):
        _validate_url("ftp://example.com/data.csv")


def test_validate_url_rejects_no_scheme():
    with pytest.raises(ValueError, match="http or https"):
        _validate_url("/etc/passwd")


def test_validate_url_rejects_loopback(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="restricted address"):
        _validate_url("https://localhost/secret")


def test_validate_url_rejects_private_ip(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("10.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="restricted address"):
        _validate_url("https://internal.corp/data")


def test_validate_url_rejects_link_local(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("169.254.169.254", 80))],
    )
    with pytest.raises(ValueError, match="restricted address"):
        _validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_allows_public_ip(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    _validate_url("https://example.com/data.json")  # should not raise


# ---------------------------------------------------------------------------
# _is_restricted_ip
# ---------------------------------------------------------------------------
def test_is_restricted_ip_rejects_loopback():
    assert _is_restricted_ip("127.0.0.1") is True


def test_is_restricted_ip_rejects_private_ranges():
    assert _is_restricted_ip("10.0.0.1") is True
    assert _is_restricted_ip("172.16.0.1") is True
    assert _is_restricted_ip("192.168.1.1") is True


def test_is_restricted_ip_rejects_link_local_metadata_endpoint():
    assert _is_restricted_ip("169.254.169.254") is True


def test_is_restricted_ip_rejects_ipv4_mapped_ipv6_metadata():
    assert _is_restricted_ip("::ffff:169.254.169.254") is True


def test_is_restricted_ip_allows_ipv4_mapped_public():
    assert _is_restricted_ip("::ffff:93.184.216.34") is False


def test_is_restricted_ip_rejects_ipv6_loopback_and_link_local():
    assert _is_restricted_ip("::1") is True
    assert _is_restricted_ip("fe80::1") is True


def test_is_restricted_ip_allows_public_addresses():
    assert _is_restricted_ip("93.184.216.34") is False
    assert _is_restricted_ip("2606:2800:220:1:248:1893:25c8:1946") is False


# ---------------------------------------------------------------------------
# _RevalidatingRedirectHandler
# ---------------------------------------------------------------------------
def test_redirect_handler_rejects_redirect_to_restricted_address(monkeypatch):
    def fake_getaddrinfo(host, *_a, **_kw):
        if host == "attacker-redirect.test":
            return [(None, None, None, None, ("169.254.169.254", 80))]
        raise AssertionError(f"unexpected host: {host}")

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)

    handler = _RevalidatingRedirectHandler()
    with pytest.raises(ValueError, match="restricted address"):
        handler.redirect_request(
            req=None,
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="http://attacker-redirect.test/latest/meta-data/",
        )


def test_redirect_handler_allows_redirect_to_public_address(monkeypatch):
    import urllib.request

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("93.184.216.34", 443))],
    )

    handler = _RevalidatingRedirectHandler()
    req = urllib.request.Request("https://example.com/original")
    result = handler.redirect_request(
        req=req,
        fp=None,
        code=302,
        msg="Found",
        headers={},
        newurl="https://example.com/next",
    )
    assert result is not None


# ---------------------------------------------------------------------------
# _ValidatingHTTPConnection / _ValidatingHTTPSConnection
# ---------------------------------------------------------------------------
def test_validating_http_connection_rejects_restricted_address_on_connect(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("169.254.169.254", 80))],
    )
    conn = _ValidatingHTTPConnection("attacker-controlled.test", 80)
    with pytest.raises(ValueError, match="restricted address"):
        conn.connect()


def test_validating_https_connection_rejects_restricted_address_on_connect(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    conn = _ValidatingHTTPSConnection("attacker-controlled.test", 443)
    with pytest.raises(ValueError, match="restricted address"):
        conn.connect()


# ---------------------------------------------------------------------------
# _build_safe_opener
# ---------------------------------------------------------------------------
def test_safe_opener_ignores_environment_proxy(monkeypatch):
    import urllib.request

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:8080")

    opener = _build_safe_opener()

    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers)


# ---------------------------------------------------------------------------
# _load_records_from_file — limit enforcement
# ---------------------------------------------------------------------------
def test_load_records_respects_limit_csv(tmp_path):
    rows = "id,val\n" + "\n".join(f"{i},v{i}" for i in range(50))
    f = tmp_path / "big.csv"
    f.write_text(rows)

    records, error = _load_records_from_file(f, limit=5)

    assert error is None
    assert len(records) == 5


def test_load_records_respects_limit_jsonl(tmp_path):
    lines = "\n".join(json.dumps({"i": i}) for i in range(50))
    f = tmp_path / "big.jsonl"
    f.write_text(lines)

    records, error = _load_records_from_file(f, limit=3)

    assert error is None
    assert len(records) == 3
