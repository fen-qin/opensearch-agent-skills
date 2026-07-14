"""Data-driven metrics for evaluating document processing (chunking) quality.

This module is intentionally dependency-free (no Docling, no cluster): it computes
metrics from already-produced chunk records, so it can be unit-tested in isolation.
The runner that actually invokes Docling lives in ``eval_runner`` / the CLI and feeds
its chunk output here.
"""

from __future__ import annotations

from statistics import median


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token), good enough for relative metrics."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def compute_metrics(chunks: list[dict], source_text_chars: int | None = None) -> dict:
    """Compute quality metrics for a list of chunk records.

    Args:
        chunks: chunk dicts as produced by ``process_document`` (text/headings/
            page_number/has_tables/...).
        source_text_chars: optional total extractable characters in the source, used
            to compute coverage (chars captured in chunks / source chars).

    Returns a metrics dict with deterministic, JSON-serializable values.
    """
    n = len(chunks)
    if n == 0:
        return {
            "chunk_count": 0,
            "avg_tokens": 0,
            "median_tokens": 0,
            "max_tokens": 0,
            "min_tokens": 0,
            "pct_chunks_with_headings": 0.0,
            "chunks_with_tables": 0,
            "total_chars": 0,
            "coverage": None,
        }

    token_counts = [estimate_tokens(c.get("text", "")) for c in chunks]
    total_chars = sum(len(c.get("text", "")) for c in chunks)
    with_headings = sum(1 for c in chunks if c.get("headings"))
    with_tables = sum(1 for c in chunks if c.get("has_tables"))
    with_images = sum(1 for c in chunks if c.get("has_image_descriptions"))

    metrics = {
        "chunk_count": n,
        "avg_tokens": round(sum(token_counts) / n, 1),
        "median_tokens": int(median(token_counts)),
        "max_tokens": max(token_counts),
        "min_tokens": min(token_counts),
        "pct_chunks_with_headings": round(100.0 * with_headings / n, 1),
        "chunks_with_tables": with_tables,
        "chunks_with_image_descriptions": with_images,
        "total_chars": total_chars,
    }

    if source_text_chars and source_text_chars > 0:
        # Coverage can exceed 1.0 when table markdown / heading context is added to
        # chunk text; cap the reported ratio at a sane ceiling for readability.
        metrics["coverage"] = round(min(total_chars / source_text_chars, 9.99), 3)
    else:
        metrics["coverage"] = None

    return metrics


# ---------------------------------------------------------------------------
# Chunk sampling (material for the agent/LLM judge — no scoring here)
# ---------------------------------------------------------------------------

def sample_chunks(chunks: list[dict], max_samples: int = 8, text_cap: int = 600) -> list[dict]:
    """Return a representative, evenly-spread sample of chunks for an LLM to judge.

    Picks up to ``max_samples`` chunks spread across the document (first, last, and
    evenly-spaced in between), preferring chunks that carry profile-effect signals
    (tables/images) so the judge sees them. Text is capped to ``text_cap`` chars.
    """
    n = len(chunks)
    if n == 0:
        return []

    idxs: list[int] = []
    # Always include chunks with tables/image descriptions (the profile's effect).
    for i, c in enumerate(chunks):
        if c.get("has_tables") or c.get("has_image_descriptions"):
            idxs.append(i)
    # Evenly spread the remainder (including first and last).
    if n <= max_samples:
        idxs.extend(range(n))
    else:
        step = (n - 1) / (max_samples - 1)
        idxs.extend(round(k * step) for k in range(max_samples))
    # De-dup, keep order, cap count.
    seen = set()
    ordered = []
    for i in sorted(idxs):
        if i not in seen and 0 <= i < n:
            seen.add(i)
            ordered.append(i)
    ordered = ordered[:max_samples]

    out = []
    for i in ordered:
        c = chunks[i]
        text = c.get("text", "") or ""
        out.append({
            "chunk_id": c.get("chunk_id", i),
            "page_number": c.get("page_number"),
            "headings": c.get("headings", []),
            "has_tables": bool(c.get("has_tables")),
            "has_image_descriptions": bool(c.get("has_image_descriptions")),
            "text": text[:text_cap] + ("…" if len(text) > text_cap else ""),
        })
    return out


def render_scorecard(results: list[dict]) -> str:
    """Render a facts-only markdown scorecard from per-fixture eval results.

    Reports objective measurements only — qualitative judgment is performed by the
    agent (LLM-as-judge), not by hard-coded rules. Each result looks like:
        {"file": ..., "profile": ..., "processing_seconds": ..., "metrics": {...},
         "error": <optional str>}
    """
    lines = ["# Document Processing Metrics", ""]
    lines.append(
        "| File | Profile | Chunks | Avg tok | Median tok | % w/ headings | Tables | Images | Coverage | Time (s) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        if r.get("error"):
            lines.append(
                f"| {r.get('file','?')} | {r.get('profile','?')} | ERROR: {r['error']} ||||||||"
            )
            continue
        m = r.get("metrics", {})
        cov = m.get("coverage")
        cov_str = "—" if cov is None else f"{cov}"
        lines.append(
            f"| {r.get('file','?')} | {r.get('profile','?')} | {m.get('chunk_count',0)} | "
            f"{m.get('avg_tokens',0)} | {m.get('median_tokens',0)} | "
            f"{m.get('pct_chunks_with_headings',0)} | {m.get('chunks_with_tables',0)} | "
            f"{m.get('chunks_with_image_descriptions',0)} | "
            f"{cov_str} | {r.get('processing_seconds','—')} |"
        )
    lines.append("")
    lines.append("_Qualitative quality is judged by the agent (LLM-as-judge) via `eval-document` → `save-quality`._")
    return "\n".join(lines)
