"""Agent-judged document-processing quality (no hard-coded scoring, no Bedrock).

Flow:
1. ``build_eval_payload(index)`` reads the locally-produced chunks for an index and
   returns objective metrics + a representative chunk sample. The conversational
   agent (LLM) reads this and judges processing quality per profile.
2. ``save_verdict(index, verdict)`` persists the agent's verdict to
   ``.opensearch/chunks/<index>/_quality.json`` so the UI can display it (cached;
   chunk output is deterministic, so one judgment per index/profile suffices).
"""

from __future__ import annotations

import json
from pathlib import Path

from lib.eval_document_processing import compute_metrics, sample_chunks

STATUS_DIR = ".opensearch"
QUALITY_FILE = "_quality.json"

# Per-profile judging dimensions (aligned with document-parsing benchmarks:
# text fidelity / reading order / table structure / completeness — judged
# semantically by the agent rather than against ground truth).
RUBRIC = {
    "semantic": ["text_fidelity", "reading_order", "chunk_boundaries", "heading_structure"],
    "tables": ["table_structure", "table_content_fidelity", "text_fidelity", "completeness"],
    "scanned": ["ocr_text_fidelity", "reading_order", "completeness"],
    "multimodal": ["image_descriptions", "text_fidelity", "reading_order", "completeness"],
}


def _index_dir(index_name: str) -> Path:
    return Path(STATUS_DIR) / "chunks" / index_name


def load_chunks(index_name: str) -> list[dict]:
    """Load all chunk records for an index from .opensearch/chunks/<index>/*.jsonl."""
    d = _index_dir(index_name)
    chunks: list[dict] = []
    if d.is_dir():
        for f in sorted(d.glob("*.jsonl")):
            for line in f.read_text().strip().split("\n"):
                if line:
                    chunks.append(json.loads(line))
    return chunks


def _read_metadata(index_name: str) -> dict:
    meta = _index_dir(index_name) / "_metadata.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text())
        except Exception:
            return {}
    return {}


def build_eval_payload(index_name: str, max_samples: int = 8) -> dict:
    """Return material for the agent to judge: profile, metrics, rubric, chunk sample."""
    chunks = load_chunks(index_name)
    if not chunks:
        return {"error": f"No chunks found for index '{index_name}'. Run `ingest` first."}
    meta = _read_metadata(index_name)
    profile = meta.get("profile", "semantic")
    metrics = compute_metrics(chunks)
    return {
        "index": index_name,
        "profile": profile,
        "source_file": Path(meta.get("source_path", "")).name,
        "pages_processed": meta.get("pages_processed") or meta.get("total_pages"),
        "metrics": metrics,
        "judge_dimensions": RUBRIC.get(profile, RUBRIC["semantic"]),
        "chunk_sample": sample_chunks(chunks, max_samples=max_samples),
        "instructions": (
            "You are judging how well this document was processed for its profile. "
            "For each dimension give a rating in {good, fair, poor} with a one-line note. "
            "Then give an overall verdict in {great, good, fair, needs_attention}, a short "
            "summary, and concrete recommendations. Judge semantically, not by fixed rules."
        ),
    }


def validate_verdict(verdict: dict) -> tuple[bool, str]:
    """Validate the agent's verdict structure before persisting."""
    if not isinstance(verdict, dict):
        return False, "verdict must be a JSON object"
    overall = verdict.get("overall")
    if overall not in {"great", "good", "fair", "needs_attention"}:
        return False, "overall must be one of: great, good, fair, needs_attention"
    dims = verdict.get("dimensions")
    if not isinstance(dims, list) or not dims:
        return False, "dimensions must be a non-empty list"
    for d in dims:
        if not isinstance(d, dict) or "name" not in d or d.get("rating") not in {"good", "fair", "poor"}:
            return False, "each dimension needs name + rating in {good, fair, poor}"
    if not isinstance(verdict.get("summary", ""), str):
        return False, "summary must be a string"
    return True, ""


def save_verdict(index_name: str, verdict: dict) -> dict:
    """Persist the agent verdict to .opensearch/chunks/<index>/_quality.json."""
    d = _index_dir(index_name)
    if not d.is_dir():
        return {"error": f"No chunks directory for index '{index_name}'."}
    ok, msg = validate_verdict(verdict)
    if not ok:
        return {"error": f"Invalid verdict: {msg}"}
    import time
    verdict = dict(verdict)
    verdict.setdefault("judged_by", "agent")
    verdict["judged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = d / QUALITY_FILE
    path.write_text(json.dumps(verdict, indent=2))
    return {"status": "saved", "index": index_name, "path": str(path)}


def read_verdict(index_name: str) -> dict | None:
    """Read a previously-saved verdict, or None if not yet judged."""
    path = _index_dir(index_name) / QUALITY_FILE
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None
