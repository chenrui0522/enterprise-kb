"""Concurrent SSE chat smoke test.

Usage: python scripts/perf_smoke.py [--url http://127.0.0.1:8000] [--concurrency 50]

Measures end-to-end wall time for `concurrency` simultaneous multi-turn-ish chat
requests and reports per-request success/errors. Requires a running API + model
services; uses a question that triggers retrieval (and rerank cap on the CPU side).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx


async def one_request(client: httpx.AsyncClient, url: str, question: str) -> tuple[str, float]:
    started = time.perf_counter()
    try:
        async with client.stream(
            "POST",
            f"{url}/api/v1/chat/stream",
            json={"message": question},
            timeout=None,
        ) as response:
            status = str(response.status_code)
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if payload["event"] == "error":
                        status = "error:" + str(payload["data"])
                    elif payload["event"] == "done" and payload["data"].get("error"):
                        status = "stream_error"
    except Exception as exc:  # keep the run going and report per-request errors
        status = f"exception:{type(exc).__name__}"
    return status, time.perf_counter() - started


async def run(url: str, concurrency: int, question: str) -> None:
    async with httpx.AsyncClient() as client:
        started = time.perf_counter()
        results = await asyncio.gather(
            *[one_request(client, url, question) for _ in range(concurrency)]
        )
        elapsed = time.perf_counter() - started
    errors = [item for item in results if not item[0].startswith("2")]
    latencies = [item[1] for item in results]
    print(f"concurrency={concurrency} total={elapsed:.2f}s")
    print(f"success={concurrency - len(errors)}/{concurrency} errors={len(errors)}")
    if latencies:
        print(f"avg={sum(latencies) / len(latencies):.2f}s min={min(latencies):.2f}s max={max(latencies):.2f}s")
    if errors:
        print("error samples:", errors[:5])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--question", default="ZB-100 打印机保修期是多久？")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.concurrency, args.question))


if __name__ == "__main__":
    main()
