"""Inspect pyc structure and try pylingual.io upload."""
from __future__ import annotations

import json
import marshal
import types
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYC_DIR = ROOT / "app" / "attendance_summary" / "__pycache__"
OUT = Path(r"C:\Users\chenr\AppData\Local\Temp\recovery\inspect")
OUT.mkdir(parents=True, exist_ok=True)


def load_code(pyc: Path) -> types.CodeType:
    data = pyc.read_bytes()
    # CPython 3.7+: magic(4) + flags(4) + hash/timestamp(8) = 16
    return marshal.loads(data[16:])


def walk(code: types.CodeType, prefix: str = "") -> None:
    print(f"{prefix}{code.co_name} args={code.co_argcount} vars={list(code.co_varnames[:12])}")
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            walk(c, prefix + "  ")


def dump_strings(code: types.CodeType, out: list[str]) -> None:
    for c in code.co_consts:
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, types.CodeType):
            dump_strings(c, out)


def try_pylingual(pyc: Path) -> None:
    urls = [
        "https://pylingual.io/api/decompile",
        "https://pylingual.io/decompile",
        "https://www.pylingual.io/api/decompile",
    ]
    data = pyc.read_bytes()
    boundary = "----Boundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{pyc.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    for url in urls:
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = r.read()
                print(url, r.status, resp[:300])
                (OUT / f"pylingual_{pyc.stem}.bin").write_bytes(resp)
        except Exception as e:
            print(url, type(e).__name__, e)


def main() -> None:
    for pyc in sorted(PYC_DIR.glob("*.pyc")):
        print("=" * 60, pyc.name)
        code = load_code(pyc)
        walk(code)
        strs: list[str] = []
        dump_strings(code, strs)
        (OUT / f"{pyc.stem}_strings.txt").write_text(
            "\n".join(strs), encoding="utf-8"
        )
        print("strings", len(strs))

    compute = PYC_DIR / "compute.cpython-312.pyc"
    print("\nTrying pylingual for compute...")
    try_pylingual(compute)


if __name__ == "__main__":
    main()
