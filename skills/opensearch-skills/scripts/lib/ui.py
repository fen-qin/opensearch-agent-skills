"""Search Builder UI server for Agent Skills standalone path.

Serves the static React frontend and proxies search requests to OpenSearch.
Matches the MCP path's full-featured search UI with smart field detection,
semantic/hybrid search, agentic search, suggestions, and autocomplete.
"""

import json
import os
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .client import create_client, create_remote_client, can_connect
from .search import (
    autocomplete,
    extract_index_field_specs,
    generate_agent_prompts,
    generate_suggestions,
    detect_index_profile,
    search_ui_search,
)

SEARCH_UI_HOST = os.getenv("SEARCH_UI_HOST", "127.0.0.1")
SEARCH_UI_PORT = int(os.getenv("SEARCH_UI_PORT", "8765"))

# Find UI static assets - bundled alongside this script
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
SEARCH_UI_STATIC_DIR = _SCRIPT_DIR / "ui"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".jsx": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}

# Mutable state — set once at launch time, immutable for the lifetime of the server.
_default_index = ""
_endpoint_override = {}  # {host, port, use_ssl, username, password, aws_region, aws_service}
_comparison_config = {
    "comparison_enabled": False,
    "baseline_index": "",
    "improved_index": "",
}

# UI mode controls which views are available:
#   "full"      -> both ingestion and search (local unstructured / launchpad)
#   "ingestion" -> ingestion (chunk inspector) only, search hidden (direct parsing)
#   "search"    -> search only, ingestion hidden (structured data, or remote/cloud)
# The frontend additionally disables the ingestion view when the endpoint is
# remote or no chunks exist for the selected index.
_UI_MODES = ("full", "ingestion", "search")
_ui_mode = {"mode": "full"}


def set_ui_mode(mode: str = "full") -> str:
    """Set the UI view-availability mode. One of: full, ingestion, search."""
    global _ui_mode
    if mode not in _UI_MODES:
        mode = "full"
    _ui_mode = {"mode": mode}
    return f"UI mode set to '{mode}'."


def set_comparison_mode(baseline_index: str, improved_index: str) -> str:
    """Configure the UI server for comparison mode."""
    global _comparison_config
    if not baseline_index or not improved_index:
        return "Both baseline and improved index names are required."
    _comparison_config = {
        "comparison_enabled": True,
        "baseline_index": baseline_index,
        "improved_index": improved_index,
    }
    return f"Comparison mode enabled: '{baseline_index}' vs '{improved_index}'."


def clear_comparison_mode() -> str:
    """Disable comparison mode and clear stored index names."""
    global _comparison_config
    _comparison_config = {
        "comparison_enabled": False,
        "baseline_index": "",
        "improved_index": "",
    }
    return "Comparison mode disabled."


def _get_client():
    override = _endpoint_override
    if override.get("host"):
        return create_remote_client(
            endpoint=override["host"],
            port=override.get("port", 443),
            use_ssl=override.get("use_ssl", True),
            username=override.get("username", ""),
            password=override.get("password", ""),
            aws_region=override.get("aws_region", ""),
            aws_service=override.get("aws_service", ""),
        )
    return create_client()


def _resolve_asset(path: str) -> Path | None:
    if not SEARCH_UI_STATIC_DIR.exists():
        return None
    clean = path.lstrip("/") or "index.html"
    target = (SEARCH_UI_STATIC_DIR / clean).resolve()
    if target.is_file() and str(target).startswith(str(SEARCH_UI_STATIC_DIR)):
        return target
    return None


def _has_local_chunks(index_name: str) -> bool:
    """True if the index has local Docling chunk files under
    .opensearch/chunks/<index>/*.jsonl. This is the sole signal that gates the
    ingestion (Chunk Inspector) tab: chunk files only exist for locally-processed
    unstructured data. Structured indexes and remote/cloud endpoints have none,
    so they get search-only automatically.
    """
    if not index_name:
        return False
    try:
        chunks_dir = Path(".opensearch") / "chunks" / index_name
        return chunks_dir.is_dir() and any(chunks_dir.glob("*.jsonl"))
    except Exception:
        return False


_ALLOWED_HOSTNAMES = ("127.0.0.1", "localhost")


class _UIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress request logging

    def _is_allowed_origin(self) -> str | None:
        """Return the Origin if it's from a loopback address, else None."""
        origin = self.headers.get("Origin", "")
        if not origin:
            return None
        try:
            parsed = urlparse(origin)
            if parsed.hostname in _ALLOWED_HOSTNAMES:
                return origin
        except Exception:
            pass
        return None

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self._is_allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        origin = self._is_allowed_origin()
        if not origin:
            self.send_error(403, "Forbidden: origin not allowed")
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Health check
        if parsed.path in ("/_health", "/api/health"):
            backend = _get_backend_info()
            self._send_json({
                "ok": True,
                "status": "running",
                "default_index": _default_index,
                "pid": os.getpid(),
                "backend_type": backend["backend_type"],
                "endpoint": backend["endpoint"],
                "connected": backend["connected"],
            })
            return

        # Config
        if parsed.path == "/api/config":
            backend = _get_backend_info()
            # Ingestion tab shows only for a local endpoint whose selected index
            # has an inspectable chunk set — either chunks under the same name,
            # or a recorded provenance parent (e.g. docs-v1 built from "docs").
            # Remote/cloud endpoints can't read local chunk files -> search-only.
            cfg_index = (params.get("index") or [""])[0] or _default_index
            is_local_endpoint = backend["backend_type"] == "local"
            chunk_source = ""
            if is_local_endpoint:
                try:
                    from .ingest import resolve_chunk_source
                    chunk_source = resolve_chunk_source(cfg_index)
                except Exception:
                    chunk_source = cfg_index if _has_local_chunks(cfg_index) else ""
            self._send_json({
                "default_index": _default_index,
                "backend_type": backend["backend_type"],
                "endpoint": backend["endpoint"],
                "connected": backend["connected"],
                "ui_mode": _ui_mode["mode"],
                "show_ingestion_tab": bool(chunk_source),
                # Chunk set the ingestion view should default to for this index
                # (same name, or the provenance parent). "" when none.
                "ingestion_chunk_index": chunk_source,
            })
            return

        # Comparison config
        if parsed.path == "/api/comparison-config":
            self._send_json(_comparison_config)
            return

        # List available indices (cluster + local chunk dirs, merged).
        if parsed.path == "/api/indices":
            merged = {}  # name -> {"name","docs","health","source"}

            # Cluster indices (best-effort; may be unavailable in local/ingestion-only).
            cluster_error = None
            try:
                client = _get_client()
                for idx in client.cat.indices(format="json"):
                    name = str(idx.get("index", ""))
                    if not name or name.startswith("."):
                        continue
                    merged[name] = {
                        "name": name,
                        "docs": idx.get("docs.count", "0"),
                        "health": idx.get("health", ""),
                        "source": "cluster",
                    }
            except Exception as e:
                cluster_error = str(e)

            # Local chunk indexes from .opensearch/chunks/<index>/
            try:
                chunks_root = Path(".opensearch") / "chunks"
                if chunks_root.is_dir():
                    for d in sorted(chunks_root.iterdir()):
                        if not d.is_dir():
                            continue
                        name = d.name
                        chunk_files = list(d.glob("*.jsonl"))
                        chunk_count = sum(
                            sum(1 for _ in f.open()) for f in chunk_files
                        ) if chunk_files else 0
                        profile = "semantic"
                        meta = d / "_metadata.json"
                        if meta.exists():
                            try:
                                import json as _json
                                profile = _json.loads(meta.read_text()).get("profile", "semantic")
                            except Exception:
                                pass
                        if name in merged:
                            merged[name]["source"] = "both"
                            merged[name]["local_chunks"] = chunk_count
                            merged[name]["profile"] = profile
                        else:
                            merged[name] = {
                                "name": name,
                                "docs": str(chunk_count),
                                "health": "",
                                "source": "local",
                                "local_chunks": chunk_count,
                                "profile": profile,
                            }
            except Exception:
                pass

            payload = {"indices": sorted(merged.values(), key=lambda x: x["name"])}
            if cluster_error and not merged:
                payload["error"] = cluster_error
            self._send_json(payload)
            return

        # Suggestions
        if parsed.path == "/api/suggestions":
            index_name = (params.get("index") or [""])[0] or _default_index
            try:
                client = _get_client()
                gen = generate_suggestions(client, index_name, max_count=8)
                result = {
                    "suggestions": gen.get("suggestions", []),
                    "sample_docs": gen.get("sample_docs", []),
                    "has_semantic": gen.get("has_semantic", False),
                    "index": index_name,
                }
                self._send_json(result)
            except Exception as e:
                self._send_json({"suggestions": [], "sample_docs": [], "has_semantic": False, "index": index_name, "error": str(e)})
            return

        # Autocomplete
        if parsed.path == "/api/autocomplete":
            index_name = (params.get("index") or [""])[0] or _default_index
            prefix_text = (params.get("q") or [""])[0]
            field_name = (params.get("field") or [""])[0]
            try:
                ac_size = int((params.get("size") or ["8"])[0])
            except ValueError:
                ac_size = 8
            ac_size = max(1, min(ac_size, 20))
            try:
                client = _get_client()
                result = autocomplete(
                    client, index_name, prefix_text,
                    size=ac_size, preferred_field=field_name,
                )
                self._send_json(result)
            except Exception as e:
                self._send_json({
                    "index": index_name, "prefix": prefix_text,
                    "field": "", "options": [], "error": str(e),
                })
            return

        # Schema / template detection
        if parsed.path == "/api/schema":
            index_name = (params.get("index") or [""])[0] or _default_index
            if not index_name:
                self._send_json({"error": "No index specified."}, 400)
                return
            try:
                client = _get_client()
                schema = detect_index_profile(client, index_name)
                schema["index"] = index_name
                self._send_json(schema)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        # Agent prompts
        if parsed.path == "/api/agent-prompts":
            index_name = (params.get("index") or [""])[0] or _default_index
            try:
                client = _get_client()
                prompts = generate_agent_prompts(client, index_name)
                self._send_json(prompts)
            except Exception as e:
                self._send_json({"search": [], "chat": [], "error": str(e)})
            return


        # Ingestion status
        if parsed.path == "/api/ingestion-status":
            from .ingest import read_status
            self._send_json(read_status())
            return

        # Serve PDF file for client-side rendering via PDF.js (index-aware)
        if parsed.path == "/api/pdf-file":
            import json as _json
            index_name = (params.get("index") or [""])[0] or _default_index
            # Security: resolve source_path only via _metadata.json — never
            # accept a user-supplied file path. Validate the index stays under
            # .opensearch/chunks/ to prevent path traversal.
            chunks_base = Path(".opensearch", "chunks").resolve()
            meta_path = (chunks_base / index_name / "_metadata.json")
            if not meta_path.resolve().is_relative_to(chunks_base):
                self._send_json({"error": "Invalid index"}, status=400)
                return
            source_file = ""
            if meta_path.exists():
                meta = _json.loads(meta_path.read_text())
                source_file = meta.get("source_path", "")
            # Fallback to ingestion status
            if not source_file:
                from .ingest import read_status
                status = read_status()
                source_file = status.get("source_path", "")
            if source_file and Path(source_file).exists():
                pdf_path = Path(source_file).resolve()
                # Verify the file is a PDF (basic extension check)
                if pdf_path.suffix.lower() != ".pdf":
                    self._send_json({"error": "Not a PDF file"}, status=400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(pdf_path.stat().st_size))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(pdf_path.read_bytes())
            else:
                self._send_json({"error": "PDF file not found"}, status=404)
            return

        # List indices that have chunks (for ingestion view dropdown)
        if parsed.path == "/api/ingestion-indices":
            chunks_root = Path(".opensearch") / "chunks"
            indices = []
            if chunks_root.exists():
                for d in sorted(chunks_root.iterdir()):
                    if d.is_dir() and list(d.glob("*.jsonl")):
                        chunk_count = sum(1 for f in d.glob("*.jsonl") for _ in open(f))
                        indices.append({"name": d.name, "chunks": chunk_count})
            self._send_json({"indices": indices})
            return

        # Ingestion chunks (for preview) — index-aware
        if parsed.path == "/api/ingestion-chunks":
            import json as _json
            # Get index from query param, fall back to default index
            index_name = (params.get("index") or [""])[0] or _default_index

            # Look for chunks in .opensearch/chunks/<index>/
            chunks_dir = Path(".opensearch") / "chunks" / index_name
            chunks = []
            all_chunks = []  # full set for accurate metrics/quality
            total_lines = 0

            if chunks_dir.exists():
                # Read all .jsonl files in the index directory
                for jsonl_file in sorted(chunks_dir.glob("*.jsonl")):
                    for line in open(jsonl_file):
                        line = line.strip()
                        if not line:
                            continue
                        total_lines += 1
                        rec = _json.loads(line)
                        all_chunks.append(rec)
                        if len(chunks) < 50:  # limit to 50 for UI preview
                            chunks.append(rec)

            # Read profile + source info from per-index metadata if present
            profile = "semantic"
            source_name = ""
            source_pages = None
            meta_path = chunks_dir / "_metadata.json"
            if meta_path.exists():
                try:
                    _meta = _json.loads(meta_path.read_text())
                    profile = _meta.get("profile", "semantic")
                    sp = _meta.get("source_path", "")
                    source_name = Path(sp).name if sp else ""
                    source_pages = _meta.get("pages_processed") or _meta.get("total_pages")
                except Exception:
                    pass

            if chunks:
                # Compute summary stats (legacy fields kept for compatibility)
                token_counts = []
                sections = set()
                for c in chunks:
                    text = c.get("text", "")
                    token_counts.append(len(text.split()))
                    for h in c.get("headings", []):
                        sections.add(h)
                avg_tokens = int(sum(token_counts) / len(token_counts)) if token_counts else 0
                histogram = {"0-100": 0, "101-300": 0, "301-512": 0, "513+": 0}
                for t in token_counts:
                    if t <= 100: histogram["0-100"] += 1
                    elif t <= 300: histogram["101-300"] += 1
                    elif t <= 512: histogram["301-512"] += 1
                    else: histogram["513+"] += 1

                # Objective metrics (facts). Qualitative judgment is the agent's
                # cached verdict (_quality.json), not a hard-coded score.
                metrics = {}
                try:
                    from lib.eval_document_processing import compute_metrics
                    # Source extractable chars (for coverage), best-effort via pypdf.
                    # Limit to the pages actually processed so coverage compares
                    # like-for-like (chunks from N pages vs. source text of those N pages).
                    src_chars = None
                    try:
                        meta2 = _json.loads(meta_path.read_text()) if meta_path.exists() else {}
                        sp2 = meta2.get("source_path", "")
                        pages_done = meta2.get("pages_processed") or meta2.get("total_pages")
                        if sp2 and Path(sp2).exists():
                            from pypdf import PdfReader as _R
                            pgs = _R(sp2).pages
                            if isinstance(pages_done, int) and pages_done > 0:
                                pgs = pgs[:pages_done]
                            src_chars = sum(len((p.extract_text() or "")) for p in pgs) or None
                    except Exception:
                        src_chars = None
                    metrics = compute_metrics(all_chunks, src_chars)
                except Exception:
                    pass

                # Cached agent verdict, if it has been judged.
                verdict = None
                try:
                    from lib.quality import read_verdict
                    verdict = read_verdict(index_name)
                except Exception:
                    verdict = None

                self._send_json({
                    "chunks": chunks,
                    "total": total_lines,
                    "showing": len(chunks),
                    "index": index_name,
                    "profile": profile,
                    "source_name": source_name,
                    "source_pages": source_pages,
                    "summary": {
                        "avg_tokens": avg_tokens,
                        "sections": len(sections),
                        "section_names": sorted(sections)[:20],
                        "tokens_avg_est": metrics.get("avg_tokens"),
                        "tokens_median_est": metrics.get("median_tokens"),
                        "pct_chunks_with_headings": metrics.get("pct_chunks_with_headings"),
                        "chunks_with_tables": metrics.get("chunks_with_tables", 0),
                        "chunks_with_image_descriptions": metrics.get("chunks_with_image_descriptions", 0),
                        "coverage": metrics.get("coverage"),
                    },
                    "quality": None,
                    "verdict": verdict,
                    "histogram": histogram,
                })
            else:
                self._send_json({"chunks": [], "total": 0, "index": index_name, "profile": profile, "summary": {}, "quality": {}, "histogram": {}})
            return

        # Search API
        if parsed.path == "/api/search":
            self._handle_search(params)
            return

        # Static file
        asset = _resolve_asset(parsed.path)
        if asset is None:
            asset = _resolve_asset("/index.html")
        if asset is None:
            self.send_error(404)
            return

        content_type = _CONTENT_TYPES.get(asset.suffix, "application/octet-stream")
        body = asset.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/search":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            self._handle_search_post(body)
            return
        if parsed.path == "/api/connect":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            result = connect_ui(
                endpoint=body.get("endpoint", ""),
                port=body.get("port", 443),
                use_ssl=body.get("use_ssl", True),
                username=body.get("username", ""),
                password=body.get("password", ""),
                aws_region=body.get("aws_region", ""),
                aws_service=body.get("aws_service", ""),
                index_name=body.get("index", ""),
            )
            self._send_json({"result": result})
            return
        self.send_error(404)

    def _handle_search(self, params: dict):
        query = (params.get("q") or params.get("query") or [""])[0]
        index = (params.get("index") or [_default_index])[0] or _default_index
        search_intent = (params.get("intent") or [""])[0]
        field_hint = (params.get("field") or [""])[0]
        memory_id_param = (params.get("memory_id") or [""])[0]
        debug_param = (params.get("debug") or ["0"])[0].strip().lower()
        debug_mode = debug_param in {"1", "true", "yes", "on"}
        try:
            size = int((params.get("size") or ["20"])[0])
        except ValueError:
            size = 20
        size = max(1, min(size, 50))

        if not index:
            self._send_json({"error": "No index specified."}, 400)
            return

        try:
            client = _get_client()
            result = search_ui_search(
                client=client,
                index_name=index,
                query_text=query,
                size=size,
                debug=debug_mode,
                search_intent=search_intent,
                field_hint=field_hint,
                memory_id=memory_id_param,
            )
            self._send_json(result)
        except Exception as e:
            self._send_json({
                "error": str(e),
                "hits": [], "took_ms": 0,
                "query_mode": "", "capability": "",
                "used_semantic": False, "fallback_reason": "",
            }, status=500)

    def _handle_search_post(self, body: dict):
        index = body.pop("index", _default_index) or _default_index
        size = body.pop("size", 20)
        if not index:
            self._send_json({"error": "No index specified."}, 400)
            return
        try:
            client = _get_client()
            # If the POST body has a "query" key, treat as raw DSL pass-through
            if "query" in body:
                result = client.search(index=index, body=body, size=size)
                self._send_json(result)
            else:
                # Otherwise treat as a structured search request
                query_text = body.get("q", body.get("query_text", ""))
                debug = body.get("debug", False)
                result = search_ui_search(
                    client=client,
                    index_name=index,
                    query_text=query_text,
                    size=size,
                    debug=debug,
                )
                self._send_json(result)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


def _get_backend_info() -> dict:
    override = _endpoint_override
    if override.get("host"):
        endpoint = override["host"]
        backend_type = "aws" if override.get("aws_region") else "remote"
        try:
            ok, _ = can_connect(_get_client())
            connected = ok
        except Exception:
            connected = False
        return {"backend_type": backend_type, "endpoint": endpoint, "connected": connected}
    from .client import OPENSEARCH_HOST, OPENSEARCH_PORT
    endpoint = f"{OPENSEARCH_HOST}:{OPENSEARCH_PORT}"
    try:
        ok, _ = can_connect(_get_client())
        connected = ok
    except Exception:
        connected = False
    return {"backend_type": "local", "endpoint": endpoint, "connected": connected}


def _kill_existing_ui() -> None:
    """Kill any existing process listening on the UI port."""
    import subprocess
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{SEARCH_UI_PORT}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid.isdigit() and int(pid) != os.getpid():
                os.kill(int(pid), signal.SIGTERM)
        if pids:
            time.sleep(0.5)
    except Exception:
        pass


def launch_ui(
    index_name: str = "",
    endpoint: str = "",
    aws_region: str = "",
    aws_service: str = "",
    username: str = "",
    password: str = "",
    mode: str = "full",
) -> str:
    """Launch the Search Builder UI.

    Args:
        index_name: Default index to search.
        endpoint: Remote endpoint host. If empty, uses local cluster.
        aws_region: AWS region (triggers SigV4 auth via boto3 credential chain).
        aws_service: AWS service type ('aoss' or 'es').
        username: Basic auth username (for non-AWS remote clusters).
        password: Basic auth password (for non-AWS remote clusters).
        mode: UI views to expose — 'full' (ingestion+search), 'ingestion'
            (chunk inspector only), or 'search' (search only).
    """
    global _default_index, _endpoint_override

    if index_name:
        _default_index = index_name

    # Set which views are available (full / ingestion / search).
    set_ui_mode(mode)

    # Set endpoint override from explicit parameters
    if endpoint:
        # Auto-detect AWS service/region from endpoint hostname
        if not aws_service and aws_region:
            if ".aoss." in endpoint:
                aws_service = "aoss"
            elif ".es." in endpoint or ".aos." in endpoint:
                aws_service = "es"
        if not aws_region and (".aoss." in endpoint or ".es." in endpoint):
            m = re.search(r"\.([a-z]{2}-[a-z]+-\d+)\.", endpoint)
            if m:
                aws_region = m.group(1)
                if not aws_service:
                    aws_service = "aoss" if ".aoss." in endpoint else "es"

        _endpoint_override = {
            "host": endpoint,
            "port": 443 if (aws_region and aws_service) else 443,
            "use_ssl": True,
            "username": username,
            "password": password,
            "aws_region": aws_region,
            "aws_service": aws_service,
        }
    else:
        _endpoint_override = {}

    if not SEARCH_UI_STATIC_DIR.exists():
        return (
            f"Error: Search UI static directory not found at {SEARCH_UI_STATIC_DIR}. "
            "Make sure you have the full opensearch-skills skill directory."
        )

    # Kill any existing UI server on the same port
    _kill_existing_ui()

    try:
        server = ThreadingHTTPServer((SEARCH_UI_HOST, SEARCH_UI_PORT), _UIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://{SEARCH_UI_HOST}:{SEARCH_UI_PORT}"

        # Wait for ready
        import urllib.request
        for _ in range(20):
            try:
                urllib.request.urlopen(f"{url}/_health", timeout=1)
                break
            except Exception:
                time.sleep(0.25)

        label = "Chunk Inspector (ingestion-only)" if _ui_mode["mode"] == "ingestion" else "Search Builder UI"
        msg = f"{label} started at: {url}"
        if _default_index:
            msg += f"\nDefault index: {_default_index}"
        if endpoint:
            msg += f"\nEndpoint: {endpoint}"
        return msg

    except OSError as e:
        if "Address already in use" in str(e):
            url = f"http://{SEARCH_UI_HOST}:{SEARCH_UI_PORT}"
            return f"Search Builder UI already running at: {url}"
        return f"Failed to start Search UI: {e}"


def cleanup_ui() -> str:
    """Clean up the UI server and clear any stored cluster credentials."""
    from .client import clear_cluster_credentials
    clear_cluster_credentials()
    return "Search UI cleanup: the UI server runs as a daemon thread and stops when the script exits. Cluster credentials cleared."
