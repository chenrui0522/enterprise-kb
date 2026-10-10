"""Rule-first Q&A over the current leave-ledger job compute_result."""

from __future__ import annotations

import re
from typing import Any

_SUMMARY_RE = re.compile(
    r"(多少人|几个人|合计|汇总|总览|进度|告警|总共|一共)",
    re.I,
)
_PERSON_FIELD_RE = re.compile(
    r"(剩余|已休|已调休|出差|加班|合计|可调休|备注|额度)",
    re.I,
)
_ASKISH_RE = re.compile(
    r"(多少|几|谁|哪|怎么|如何|多少天|几天|剩余|已休|出差|加班|合计|汇总|进度|告警|"
    r"可调休|备注|有没有|有无|在不在|包含|在吗|台账|\?|？)",
    re.I,
)
_PRESENCE_RE = re.compile(r"(有没有|有无|在不在|包含|在吗|台账里有|台账有)", re.I)
_MERGE_HELP_RE = re.compile(
    r"(合并|上一版|上月|以往|prior|导出台账|台账卡片|卡片在哪|在哪.*(?:台账|卡片)|"
    r"(?:台账|卡片).*在哪|怎么合|如何合)",
    re.I,
)
_PRONOUN_RE = re.compile(r"(他|她|此人|该人|这人)")
_OT_DATE_ASK_RE = re.compile(r"(哪一天|哪天|哪几|哪日|日期|几号)")



def looks_like_leave_query(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 200:
        return False
    return bool(
        _ASKISH_RE.search(t)
        or _SUMMARY_RE.search(t)
        or _PERSON_FIELD_RE.search(t)
        or _PRESENCE_RE.search(t)
        or _MERGE_HELP_RE.search(t)
    )


def looks_like_merge_help(text: str) -> bool:
    return bool(_MERGE_HELP_RE.search(text or ""))


def format_merge_help(*, job_status: str, has_rows: bool, prior_option_count: int = 0) -> str:
    """Guide users to prior merge UI; no separate 'last month card'."""
    if job_status in ("confirmed", "voided"):
        return (
            "当前任务已确认（或已作废），不能再合并写回。"
            "合并必须在「确认台账」之前完成。"
            "若要接上月/上一版：请作废后重做，或新建本月任务 → 上传四源算出结果 → "
            "在进度卡选择 prior（或上传本系统正式导出台账）→ 合并写回 → 再确认。"
            "若只要下载本月正式表，点卡片「导出 Excel」。"
            "说明：没有单独的「上个月卡片」，prior 选择器在未确认任务的进度卡里。"
        )
    if not has_rows:
        return (
            "请先完成本月四源上传并算出结果，再合并上月。"
            "算出后，进度卡会出现「合并 prior」下拉；"
            "也可直接上传本系统导出的上月正式台账 xlsx，再点「用上传台账合并」。"
        )
    prior_hint = (
        f"当前可选 prior {prior_option_count} 份（确认·/导入·）。"
        if prior_option_count
        else "若下拉为空：可到专页确认过的任务会出现在列表，或直接上传本系统正式导出台账。"
    )
    return (
        "没有单独的「上个月台账卡片」。请在下方当前任务进度卡中："
        "① 用「合并 prior」下拉选择上月已确认/导入任务并点「合并写回」；"
        "② 或上传本系统导出的上月正式台账 xlsx，确认后点「用上传台账合并」。"
        f"{prior_hint}"
    )


def _extract_presence_name(text: str) -> str | None:
    t = text or ""
    m = re.search(r"(?:有没有|有无|包含)\s*([^\s？?，,。的]{1,20})", t)
    if m:
        return m.group(1).strip() or None
    m = re.search(r"([^\s？?，,。]{1,20})\s*在不在", t)
    if m:
        return m.group(1).strip() or None
    return None


def match_person_row(
    text: str, rows: list[dict[str, Any]]
) -> dict[str, Any] | None | list[dict[str, Any]]:
    """Return best row, None if no name hit, or list if multiple equal-length matches."""
    t = text or ""
    hits: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        name = str(row.get("person_name") or "").strip()
        if not name:
            continue
        if name in t:
            hits.append((len(name), row))
    if not hits:
        return None
    best_len = max(h[0] for h in hits)
    best = [h[1] for h in hits if h[0] == best_len]
    # de-dupe by person_name
    by_name: dict[str, dict[str, Any]] = {}
    for r in best:
        by_name[str(r.get("person_name") or "")] = r
    uniq = list(by_name.values())
    if len(uniq) == 1:
        return uniq[0]
    return uniq


def resolve_person_row(
    text: str,
    rows: list[dict[str, Any]],
    *,
    last_person_name: str | None = None,
) -> dict[str, Any] | None | list[dict[str, Any]]:
    """Match name in text, or resolve 他/她 to sticky last_person_name."""
    matched = match_person_row(text, rows)
    if matched is not None:
        return matched
    if not last_person_name or not _PRONOUN_RE.search(text or ""):
        return None
    for row in rows:
        if str(row.get("person_name") or "").strip() == last_person_name:
            return row
    return None


def format_ot_days_answer(name: str, row: dict[str, Any]) -> str:
    days = [
        d
        for d in (row.get("ot_days") or [])
        if float(d.get("credit") or 0) > 0
    ]
    if not days:
        ot = _fmt_num(row.get("ot_comp_days"))
        if float(row.get("ot_comp_days") or 0) > 0:
            return (
                f"{name}：加班可调休 {ot} 天，但结果中未列出具体加班日明细"
                "（可能来自导入模板汇总）。"
            )
        return f"{name}：无计入加班可调休日。"
    parts = []
    for d in days:
        date_s = str(d.get("date") or "").replace("(法定)", "").strip()
        credit = _fmt_num(d.get("credit"))
        tag = "（法定）" if d.get("holiday") or "(法定)" in str(d.get("date") or "") else ""
        parts.append(f"{date_s}{tag} {credit} 天")
    return f"{name}：加班可调休日为 " + "；".join(parts) + "。"


def _fmt_num(value: Any) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return str(value)
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def format_person_answer(text: str, row: dict[str, Any]) -> str:
    name = str(row.get("person_name") or "")
    travel = _fmt_num(row.get("travel_comp_days"))
    ot = _fmt_num(row.get("ot_comp_days"))
    total = _fmt_num(row.get("total_comp_days"))
    used = _fmt_num(row.get("used_comp_days"))
    rem = _fmt_num(row.get("remaining_comp_days"))
    remark = str(row.get("remark") or "").strip()
    t = text or ""

    if re.search(r"剩余", t) and not re.search(r"合计|出差|加班|已休", t):
        return f"{name}：剩余调休 {rem} 天。"
    if re.search(r"已休|已调休", t) and not re.search(r"剩余|出差|加班", t):
        return f"{name}：已调休 {used} 天。"
    if re.search(r"出差", t) and not re.search(r"加班|剩余|已休", t):
        return f"{name}：出差可调休 {travel} 天。"
    if re.search(r"加班", t) and not re.search(r"出差|剩余|已休", t):
        if _OT_DATE_ASK_RE.search(t):
            return format_ot_days_answer(name, row)
        return f"{name}：加班可调休 {ot} 天。"
    if re.search(r"备注", t):
        return f"{name}：备注「{remark or '（无）'}」。"

    if _PRESENCE_RE.search(t) and not _PERSON_FIELD_RE.search(t):
        return (
            f"有。{name}在当前台账中：出差可调休 {travel} 天，加班可调休 {ot} 天，"
            f"合计 {total} 天；已休 {used} 天，剩余 {rem} 天。"
        )

    lines = [
        f"{name}：出差可调休 {travel} 天，加班可调休 {ot} 天，合计 {total} 天；"
        f"已休 {used} 天，剩余 {rem} 天。"
    ]
    if remark:
        lines.append(f"备注：{remark}")
    return "\n".join(lines)


def format_task_summary(
    *,
    rows: list[dict[str, Any]],
    job_status: str,
    warning_count: int,
    open_blocking: int,
    totals: dict[str, Any] | None = None,
) -> str:
    person_count = len(rows)
    if totals:
        total_comp = _fmt_num(totals.get("total_comp_days"))
        used = _fmt_num(totals.get("used_comp_days"))
        remaining = totals.get("remaining_comp_days")
        if remaining is None:
            try:
                remaining = float(totals.get("total_comp_days") or 0) - float(
                    totals.get("used_comp_days") or 0
                )
            except (TypeError, ValueError):
                remaining = 0
        rem_s = _fmt_num(remaining)
    else:
        total_comp = _fmt_num(sum(float(r.get("total_comp_days") or 0) for r in rows))
        used = _fmt_num(sum(float(r.get("used_comp_days") or 0) for r in rows))
        rem_s = _fmt_num(sum(float(r.get("remaining_comp_days") or 0) for r in rows))
    return (
        f"当前调休任务状态：{job_status}；共 {person_count} 人；"
        f"合计可调休 {total_comp} 天，已休 {used} 天，剩余合计 {rem_s} 天；"
        f"告警 {warning_count} 条（未决议阻塞 {open_blocking}）。"
    )


def answer_leave_query(
    text: str,
    *,
    rows: list[dict[str, Any]],
    job_status: str,
    warning_count: int,
    open_blocking: int,
    totals: dict[str, Any] | None = None,
    prior_option_count: int = 0,
    last_person_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (answer, sticky_person_name). Answer None if not a handled query."""
    if not looks_like_leave_query(text):
        return None, None

    if looks_like_merge_help(text):
        return (
            format_merge_help(
                job_status=job_status,
                has_rows=bool(rows),
                prior_option_count=prior_option_count,
            ),
            last_person_name,
        )

    if not rows:
        return (
            "当前任务尚无预览行（可能仍缺源文件或尚未算出结果）。请先上传四源并完成计算。",
            last_person_name,
        )

    matched = resolve_person_row(text, rows, last_person_name=last_person_name)
    if isinstance(matched, list):
        names = "、".join(str(r.get("person_name") or "") for r in matched)
        return f"匹配到多人（{names}），请用完整姓名再问一次。", last_person_name
    if isinstance(matched, dict):
        name = str(matched.get("person_name") or "") or last_person_name
        return format_person_answer(text, matched), name

    if _PRONOUN_RE.search(text or "") and not last_person_name:
        return (
            "请先说明姓名（如「宣瑞宏加班哪一天」），或先问某人额度后再用「他/她」追问。",
            None,
        )

    if _SUMMARY_RE.search(text or ""):
        return (
            format_task_summary(
                rows=rows,
                job_status=job_status,
                warning_count=warning_count,
                open_blocking=open_blocking,
                totals=totals,
            ),
            last_person_name,
        )

    if _PRESENCE_RE.search(text or ""):
        hint = _extract_presence_name(text) or "该人"
        return f"没有。当前台账结果中未找到「{hint}」。", last_person_name

    # Askish but no person and not summary — honest fallback
    # Avoid bare「哪」(e.g. 卡片在哪) which is merge-help, not person lookup.
    if _PERSON_FIELD_RE.search(text or "") or re.search(
        r"(谁|哪个人|哪位|多少天|几天)", text or ""
    ):
        return (
            "未在当前台账结果中找到对应人员。"
            "可直接说「张三剩余调休」或「多少人/汇总」。",
            last_person_name,
        )
    return None, last_person_name
