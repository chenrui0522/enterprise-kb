"""Conversion baseline evaluation for the refine-document-conversion change.

Usage:
    uv run python scripts/eval_conversion.py                 # samples in data/conversion_eval
    uv run python scripts/eval_conversion.py --samples data/eval_docs
    uv run python scripts/eval_conversion.py --docling       # also measure Docling when reachable

For every sample file the script runs triage, then converts it with each
candidate converter (local / Docling / MinerU / xlsx-semantic) and reports
wall-clock parse time, structure size and table/image counts. The output is
written to `<samples>/conversion_results.json` so the numbers behind a routing
decision are reproducible.

Retrieval-side comparison reuses the existing recall harness: ingest the same
files into a scratch collection and run `scripts/eval_recall.py --run` against
it. This script deliberately stays on the parsing side so it can run without
Milvus or the model service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.ingestion.conversion import convert_safely  # noqa: E402
from app.ingestion.docling import DoclingConverter  # noqa: E402
from app.ingestion.mineru import MinerUConverter  # noqa: E402
from app.ingestion.tabular import XlsxSemanticConverter  # noqa: E402
from app.ingestion.triage import plan_candidates, triage_file  # noqa: E402

DEFAULT_SAMPLES = ROOT / "data" / "conversion_eval"
SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".html", ".csv", ".json", ".png", ".jpg"}


def _converter_for(label: str, settings: Settings, filename: str):
    if label == "docling":
        return DoclingConverter(settings)
    if label == "xlsx":
        return XlsxSemanticConverter()
    return None


def _candidate_labels(filename: str, settings: Settings, *, include_docling: bool) -> list[str]:
    """Converter labels to benchmark for one file, independent of availability."""
    suffix = Path(filename).suffix.lower()
    labels: list[str] = []
    if suffix in {".xlsx", ".xlsm"}:
        labels.append("xlsx")
    if include_docling:
        labels.append("docling")
    if suffix == ".pdf" and settings.mineru_enabled:
        labels.append("ocr")
    labels.append("local")
    return labels


async def _benchmark_file(
    path: Path, settings: Settings, *, include_docling: bool, include_ocr: bool = False
) -> dict:
    triage = triage_file(path, path.name)
    entry: dict = {
        "file": path.name,
        "size_kb": round(path.stat().st_size / 1024, 1),
        "triage": triage.as_report(),
        "candidates": {},
    }

    plan = plan_candidates(
        path.name,
        "auto",
        settings,
        triage,
        docling_candidate=include_docling and settings.docling_enabled,
    )
    entry["plan"] = [label for label, _ in plan]

    for label, converter in plan:
        # OCR on CPU is minutes per document; it is opt-in so a routine
        # baseline run stays comparable and quick.
        if label in {"ocr", "hybrid"} and not include_ocr:
            continue
        if label == "ocr" and not settings.mineru_enabled:
            continue
        started = time.perf_counter()
        try:
            result = await convert_safely(converter, str(path), label=label)
            elapsed = int((time.perf_counter() - started) * 1000)
            blocks = list(result.structure.blocks) if result.structure else []
            entry["candidates"][label] = {
                "ok": True,
                "elapsed_ms": elapsed,
                "markdown_chars": len(result.markdown or ""),
                "blocks": len(blocks),
                # Table blocks (PDF/DOCX) plus metadata grids (XLSX).
                "tables": len([block for block in blocks if block.type == "table"])
                + len(result.tables or []),
                "images": len(getattr(result, "images", None) or []),
                "degraded": bool(getattr(result.structure, "degraded", False)),
            }
        except AppError as exc:
            entry["candidates"][label] = {
                "ok": False,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc)[:200],
            }
    return entry


def _print_report(entries: list[dict]) -> None:
    print("\n== 转换基线评测 ==")
    for entry in entries:
        print(f"\n{entry['file']}  ({entry['size_kb']} KB)  triage={entry['triage']['kind']}")
        print(f"  plan: {' -> '.join(entry['plan'])}")
        for label, stats in entry["candidates"].items():
            if not stats.get("ok"):
                print(f"  {label:<10} FAILED  {stats.get('error', '')}")
                continue
            print(
                f"  {label:<10} {stats['elapsed_ms']:>6} ms   "
                f"chars={stats['markdown_chars']:<7} blocks={stats['blocks']:<5} "
                f"tables={stats['tables']:<3} images={stats['images']:<3}"
                f"{' (degraded)' if stats['degraded'] else ''}"
            )
    availability = {}
    for entry in entries:
        for label, stats in entry["candidates"].items():
            bucket = availability.setdefault(label, {"ok": 0, "failed": 0, "ms": []})
            if stats.get("ok"):
                bucket["ok"] += 1
                bucket["ms"].append(stats["elapsed_ms"])
            else:
                bucket["failed"] += 1
    if availability:
        print("\n== 汇总 ==")
        for label, bucket in sorted(availability.items()):
            average = int(sum(bucket["ms"]) / len(bucket["ms"])) if bucket["ms"] else 0
            print(f"  {label:<10} ok={bucket['ok']} failed={bucket['failed']} avg={average} ms")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Conversion baseline evaluation")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES), help="目录，默认 data/conversion_eval")
    parser.add_argument("--docling", action="store_true", help="同时评测 Docling（需服务可达）")
    parser.add_argument("--max-mb", type=float, default=20.0, help="跳过大于该体积的文件（默认 20MB）")
    parser.add_argument("--ocr", action="store_true", help="同时评测 MinerU OCR（CPU 下每篇可能数分钟）")
    args = parser.parse_args()

    samples = Path(args.samples)
    if not samples.is_dir():
        print(f"样例目录不存在：{samples}")
        print("放入任意 PDF/DOCX/PPTX/XLSX 样例后重跑，即可得到各转换器的耗时与结构对比。")
        return 1

    limit_bytes = int(args.max_mb * 1024 * 1024) if args.max_mb > 0 else 0
    files = sorted(
        path
        for path in samples.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED
        and (not limit_bytes or path.stat().st_size <= limit_bytes)
    )
    if not files:
        print(f"{samples} 下没有可评测的文件")
        return 1

    settings = Settings()
    entries = [
        await _benchmark_file(
            path, settings, include_docling=args.docling, include_ocr=args.ocr
        )
        for path in files
    ]
    _print_report(entries)

    output = samples / "conversion_results.json"
    output.write_text(
        json.dumps(
            {"settings": {"docling": args.docling, "ocr": args.ocr}, "entries": entries},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n结果已写入 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))