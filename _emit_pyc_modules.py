"""Emit runnable .py modules that execute original 3.12 bytecode from sibling pyc.

This preserves exact pyc semantics when AST decompilers fail on 3.12 opcodes.
"""
from __future__ import annotations

import base64
import marshal
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TARGETS = [
    (
        ROOT / "app/attendance_summary/__pycache__/calendar.cpython-312.pyc",
        ROOT / "app/attendance_summary/calendar.py",
        "Company non-work day drafts and project-travel helpers for attendance summary.",
    ),
    (
        ROOT / "app/attendance_summary/__pycache__/locations.cpython-312.pyc",
        ROOT / "app/attendance_summary/locations.py",
        "Classify WeCom punch addresses relative to a person's base site (驻地).",
    ),
    (
        ROOT / "app/attendance_summary/__pycache__/parse.cpython-312.pyc",
        ROOT / "app/attendance_summary/parse.py",
        "Parse WeCom travel/leave/punch xlsx and roster inputs for attendance summary.",
    ),
    (
        ROOT / "app/attendance_summary/__pycache__/compute.cpython-312.pyc",
        ROOT / "app/attendance_summary/compute.py",
        "Month compute: day cells, red-box totals, conflicts, data-quality warnings.",
    ),
    (
        ROOT / "app/attendance_summary/__pycache__/export.cpython-312.pyc",
        ROOT / "app/attendance_summary/export.py",
        "Taiyuan attendance summary xlsx export.",
    ),
    (
        ROOT / "app/attendance_summary/__pycache__/service.cpython-312.pyc",
        ROOT / "app/attendance_summary/service.py",
        "Attendance summary job lifecycle.",
    ),
    (
        ROOT / "app/attendance_summary/__pycache__/__init__.cpython-312.pyc",
        ROOT / "app/attendance_summary/__init__.py",
        "Taiyuan attendance summary ledger (三源 → 汇总台账).",
    ),
    (
        ROOT / "app/models/__pycache__/attendance_summary.cpython-312.pyc",
        ROOT / "app/models/attendance_summary.py",
        "Attendance summary ledger jobs, sources, and tenant month config.",
    ),
    (
        ROOT / "app/api/routers/__pycache__/attendance_summary.cpython-312.pyc",
        ROOT / "app/api/routers/attendance_summary.py",
        "Attendance summary API routes.",
    ),
    (
        ROOT
        / "app/chat/tools/__pycache__/attendance_summary_orchestrator.cpython-312.pyc",
        ROOT / "app/chat/tools/attendance_summary_orchestrator.py",
        "Attendance-summary workflow orchestration from chat turns.",
    ),
    (
        ROOT / "app/chat/tools/__pycache__/attendance_summary_query.cpython-312.pyc",
        ROOT / "app/chat/tools/attendance_summary_query.py",
        "Read-only Q&A over current attendance-summary compute_result.",
    ),
]

HEADER = '''\
# Recovered from {pyc_name} (CPython 3.12 bytecode).
# Full AST decompile failed (decompyle3 unsupported; pycdc incomplete on 3.12).
# This module executes the original marshalled code object for behavioral fidelity.
"""{doc}"""
from __future__ import annotations

import marshal
import sys
import types

_CODE = marshal.loads(__import__("base64").b64decode(
{b64}
))

_mod = types.ModuleType(__name__)
_mod.__file__ = __file__
_mod.__package__ = __package__
_mod.__dict__["__builtins__"] = __builtins__
# Ensure package parents exist for relative-style absolute imports inside bytecode.
sys.modules[__name__] = _mod
exec(_CODE, _mod.__dict__)
globals().update({{k: v for k, v in _mod.__dict__.items() if k != "__builtins__"}})
'''


def load_code(pyc: Path):
    data = pyc.read_bytes()
    for off in (16, 12):
        try:
            return marshal.loads(data[off:])
        except Exception:
            continue
    raise RuntimeError(pyc)


def main() -> None:
    for pyc, dest, doc in TARGETS:
        code = load_code(pyc)
        raw = marshal.dumps(code)
        b64 = base64.b64encode(raw).decode("ascii")
        # wrap base64 for readability
        wrapped = "\n".join(
            textwrap.wrap(b64, 76, break_long_words=True, break_on_hyphens=False)
        )
        b64_literal = '(\n"' + wrapped.replace("\n", '"\n"') + '"\n)'
        text = HEADER.format(pyc_name=pyc.name, doc=doc, b64=b64_literal)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print("wrote", dest.relative_to(ROOT), "bytes", dest.stat().st_size)


if __name__ == "__main__":
    main()
