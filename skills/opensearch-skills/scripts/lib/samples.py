"""Sample data loading for OpenSearch search builder."""

import csv
import http.client
import ipaddress
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .client import create_client


def _load_records_from_file(file_path: Path, limit: int = 10) -> tuple[list[dict], str | None]:
    suffix = file_path.suffix.lower()

    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
            table = pq.read_table(str(file_path))
            records = table.to_pylist()[:limit]
            return records, None
        except ImportError:
            return [], "pyarrow required for Parquet files. Install with: pip install pyarrow"
        except Exception as e:
            return [], str(e)

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            if suffix in (".json", ".jsonl", ".ndjson"):
                content = f.read().strip()
                if content.startswith("["):
                    records = json.loads(content)
                    return records[:limit], None
                # JSONL
                records = []
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
                        if len(records) >= limit:
                            break
                return records, None

            if suffix in (".csv", ".tsv"):
                delimiter = "\t" if suffix == ".tsv" else ","
                reader = csv.DictReader(f, delimiter=delimiter)
                records = []
                for row in reader:
                    records.append(dict(row))
                    if len(records) >= limit:
                        break
                return records, None

            return [], f"Unsupported file format: {suffix}"
    except Exception as e:
        return [], str(e)


def _infer_text_fields(doc: dict) -> list[str]:
    text_fields = []
    for key, value in doc.items():
        if isinstance(value, str) and len(value.split()) > 3:
            text_fields.append(key)
    return text_fields


def load_sample_builtin_imdb() -> str:
    script_dir = Path(__file__).resolve().parent.parent
    # Look for bundled sample data alongside this script
    candidates = [
        script_dir / "sample_data" / "imdb.title.basics.tsv",
    ]
    for path in candidates:
        if path.exists():
            return load_sample_from_file(str(path.resolve()))

    return json.dumps({"error": "IMDB sample data not found."})


def load_sample_from_file(file_path: str) -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    records, error = _load_records_from_file(path, limit=10)
    if error:
        return json.dumps({"error": error})
    if not records:
        return json.dumps({"error": "No records found in file."})

    sample = records[0]
    text_fields = _infer_text_fields(sample)
    return json.dumps({
        "status": "loaded",
        "source": str(path),
        "record_count": len(records),
        "sample_doc": sample,
        "text_fields": text_fields,
        "text_search_required": len(text_fields) > 0,
    }, ensure_ascii=False, default=str)


def _is_restricted_ip(ip_str: str) -> bool:
    """True if ip_str is private, loopback, link-local (includes
    169.254.0.0/16), or otherwise reserved."""
    addr = ipaddress.ip_address(ip_str)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
        or addr.is_multicast
    )


def _validate_url(url: str) -> None:
    """Only allow http/https URLs whose host resolves to a public address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve host: {hostname} ({e})")
    for info in infos:
        if _is_restricted_ip(info[4][0]):
            raise ValueError(f"URL resolves to a restricted address: {info[4][0]}")


class _RevalidatingConnectionMixin:
    """Re-checks the resolved address right before connecting."""

    def connect(self):
        for info in socket.getaddrinfo(self.host, self.port, proto=socket.IPPROTO_TCP):
            if _is_restricted_ip(info[4][0]):
                raise ValueError(f"URL resolves to a restricted address: {info[4][0]}")
        super().connect()


class _ValidatingHTTPConnection(_RevalidatingConnectionMixin, http.client.HTTPConnection):
    pass


class _ValidatingHTTPSConnection(_RevalidatingConnectionMixin, http.client.HTTPSConnection):
    pass


class _ValidatingHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_ValidatingHTTPConnection, req)


class _ValidatingHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_ValidatingHTTPSConnection, req)


class _RevalidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates each redirect target before following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_safe_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _ValidatingHTTPHandler(),
        _ValidatingHTTPSHandler(),
        _RevalidatingRedirectHandler(),
    )


def load_sample_from_url(url: str) -> str:
    try:
        _validate_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "opensearch-skills/1.0"})
        opener = _build_safe_opener()
        with opener.open(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        # Try JSON
        try:
            data = json.loads(content)
            if isinstance(data, list):
                records = data[:10]
            elif isinstance(data, dict):
                records = [data]
            else:
                return json.dumps({"error": "URL returned unexpected JSON format."})
        except json.JSONDecodeError:
            # Try CSV
            lines = content.splitlines()
            reader = csv.DictReader(lines)
            records = [dict(row) for row in list(reader)[:10]]

        if not records:
            return json.dumps({"error": "No records loaded from URL."})

        sample = records[0]
        text_fields = _infer_text_fields(sample)
        return json.dumps({
            "status": "loaded",
            "source": url,
            "record_count": len(records),
            "sample_doc": sample,
            "text_fields": text_fields,
            "text_search_required": len(text_fields) > 0,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to load from URL: {e}"})


def load_sample_from_index(index_name: str) -> str:
    try:
        client = create_client()
        resp = client.search(index=index_name, body={"query": {"match_all": {}}, "size": 10})
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            return json.dumps({"error": f"No documents in index '{index_name}'."})

        records = [hit["_source"] for hit in hits if "_source" in hit]
        sample = records[0] if records else {}
        text_fields = _infer_text_fields(sample)
        return json.dumps({
            "status": "loaded",
            "source": f"localhost:{index_name}",
            "record_count": len(records),
            "sample_doc": sample,
            "text_fields": text_fields,
            "text_search_required": len(text_fields) > 0,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to load from index: {e}"})


def load_sample_from_paste(doc_json: str) -> str:
    try:
        doc = json.loads(doc_json)
        if not isinstance(doc, dict):
            return json.dumps({"error": "Pasted data must be a JSON object."})
        text_fields = _infer_text_fields(doc)
        return json.dumps({
            "status": "loaded",
            "source": "paste",
            "record_count": 1,
            "sample_doc": doc,
            "text_fields": text_fields,
            "text_search_required": len(text_fields) > 0,
        }, ensure_ascii=False, default=str)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})
