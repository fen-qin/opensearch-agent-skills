#!/usr/bin/env python3
"""Document-processing evaluation runner (gated; requires the `ingestion` deps).

Reads the PDF fixtures manifest, runs Docling processing for each fixture using its
manifest-recommended profile, computes data-driven metrics, and writes a JSON report
plus a markdown scorecard.

Usage:
    uv run --group ingestion python scripts/eval_documents.py \
        [--manifest tests/evals/fixtures/pdfs/manifest.json] \
        [--out-dir .opensearch/eval] [--max-pages 10]

This is NOT part of the default unit-test suite (it needs Docling + model downloads).
Metric computation itself is unit-tested via lib/eval_document_processing.py.
"""

import argparse
import json
import sys
import time
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.eval_document_processing import compute_metrics, render_scorecard  # noqa: E402


def _source_text_chars(pdf_path: str, max_pages: int) -> int | None:
    """Best-effort extractable-char count of the source (for coverage)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        total = 0
        for pg in reader.pages[:max_pages]:
            try:
                total += len((pg.extract_text() or ""))
            except Exception:
                pass
        return total or None
    except Exception:
        return None


def run_eval(manifest_path: Path, out_dir: Path, max_pages: int) -> dict:
    from lib.ingest import process_document  # imported here so the dep is only needed at runtime

    manifest = json.loads(manifest_path.read_text())
    fixtures_dir = manifest_path.parent
    results = []

    for fx in manifest["fixtures"]:
        pdf = fixtures_dir / fx["file"]
        profile = fx.get("recommended_profile", "semantic")
        entry = {"file": fx["file"], "profile": profile, "doc_type": fx.get("doc_type")}
        if not pdf.exists():
            entry["error"] = "fixture file missing"
            results.append(entry)
            continue
        try:
            t0 = time.time()
            chunks = process_document(str(pdf), max_pages=max_pages, profile=profile)
            entry["processing_seconds"] = round(time.time() - t0, 2)
            entry["metrics"] = compute_metrics(chunks, _source_text_chars(str(pdf), max_pages))
        except Exception as e:  # profile may be Stage B (e.g. scanned/multimodal)
            entry["error"] = f"{type(e).__name__}: {e}"
        results.append(entry)

    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"manifest": str(manifest_path), "max_pages": max_pages, "results": results}
    (out_dir / "eval-report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "scorecard.md").write_text(render_scorecard(results))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default="tests/evals/fixtures/pdfs/manifest.json")
    ap.add_argument("--out-dir", default=".opensearch/eval")
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()

    report = run_eval(Path(args.manifest), Path(args.out_dir), args.max_pages)
    print(render_scorecard(report["results"]))
    print(f"\nJSON report: {Path(args.out_dir) / 'eval-report.json'}")
    print(f"Scorecard:   {Path(args.out_dir) / 'scorecard.md'}")


if __name__ == "__main__":
    main()
