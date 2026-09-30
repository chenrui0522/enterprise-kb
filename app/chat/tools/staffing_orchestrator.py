"""Staffing workflow orchestration from chat turns."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tools.registry import TOOL_STAFFING, ensure_tool_allowed
from app.core.config import get_settings
from app.core.errors import AppError
from app.identity.feature_gates import can_use_staffing
from app.identity.principal import Principal
from app.ingestion.storage import FileDocumentStorage
from app.models.entity import Conversation, new_id
from app.staffing import service as staffing_service

KIND_LABEL = {
    "internal_formal": "正式我司",
    "internal_contract": "机电服务处",
}


def _tool_state(conversation: Conversation) -> dict[str, Any]:
    raw = conversation.tool_state
    return dict(raw) if isinstance(raw, dict) else {}


def set_tool_state(conversation: Conversation, state: dict[str, Any] | None) -> None:
    conversation.tool_state = state


def clear_tool_state(conversation: Conversation) -> None:
    conversation.tool_state = None


def update_staffing_state(
    conversation: Conversation,
    *,
    active_tool: str | None = TOOL_STAFFING,
    batch_id: str | None = None,
    project_id: str | None = None,
) -> None:
    state = _tool_state(conversation)
    if active_tool:
        state["active_tool"] = active_tool
    staffing = dict(state.get("staffing") or {})
    if batch_id is not None:
        staffing["batch_id"] = batch_id
    if project_id is not None:
        staffing["project_id"] = project_id
    state["staffing"] = staffing
    conversation.tool_state = state


def _summary_card(summary: dict[str, Any]) -> dict[str, Any]:
    people = [
        {
            "person_name": p["person_name"],
            "person_kind": p.get("person_kind"),
            "person_kind_label": p.get("person_kind_label")
            or KIND_LABEL.get(p.get("person_kind"), p.get("person_kind")),
            "days_on_site": p["days_on_site"],
            "dates": list(p.get("dates") or []),
            "date_stages": dict(p.get("date_stages") or {}),
            "stages": list(p.get("stages") or []),
            "stint_count": p.get("stint_count") or len(p.get("stints") or []),
            "stints": list(p.get("stints") or []),
        }
        for p in (summary.get("people") or [])
    ]
    return {
        "type": "staffing_summary",
        "label": summary.get("label") or "在场天数",
        "project_id": summary.get("project_id"),
        "project_code": summary.get("project_code") or "",
        "project_name": summary.get("project_name") or "",
        "person_count": summary.get("person_count") or len(people),
        "person_day_total": summary.get("person_day_total") or 0,
        "date_from": summary.get("date_from"),
        "date_to": summary.get("date_to"),
        "by_kind": summary.get("by_kind") or {},
        "people": people,
        "name_split_suspects": list(summary.get("name_split_suspects") or []),
        "actions": [
            {"id": "export_xlsx", "label": "导出 Excel"},
            {"id": "void_prompt", "label": "作废某人…"},
        ],
    }


def _batch_card(batch, *, auto_note: str | None = None) -> dict[str, Any]:
    warnings = [
        {
            "code": w.get("code"),
            "message": w.get("message"),
            "row": w.get("row"),
            "detail": w.get("detail") if isinstance(w.get("detail"), dict) else {},
        }
        for w in (batch.warnings or [])
        if isinstance(w, dict)
    ]
    warnings.sort(
        key=lambda w: 0
        if w.get("code")
        in {
            "name_kind_collision",
            "project_unmatched",
            "project_ambiguous",
            "suspected_name_split",
            "roster_name_unresolved",
            "roster_unavailable",
        }
        else 1
    )
    collisions = [
        {
            "person_name": (w.get("detail") or {}).get("person_name"),
            "kinds": (w.get("detail") or {}).get("kinds") or [],
            "message": w.get("message"),
        }
        for w in warnings
        if w.get("code") == "name_kind_collision" and (w.get("detail") or {}).get("person_name")
    ]
    roster_unresolved = [
        {
            "token": (w.get("detail") or {}).get("token"),
            "candidates": list((w.get("detail") or {}).get("candidates") or []),
            "message": w.get("message"),
        }
        for w in warnings
        if w.get("code") == "roster_name_unresolved" and (w.get("detail") or {}).get("token")
    ]
    roster_unavailable = any(w.get("code") == "roster_unavailable" for w in warnings)
    match_info = batch.match_info if isinstance(batch.match_info, dict) else {}
    match_status = match_info.get("status") or ("matched" if batch.project_id else "unmatched")
    candidates = list(match_info.get("candidates") or [])
    needs_project = not batch.project_id
    actions = []
    if batch.status in ("needs_review", "parsed"):
        label = "选定项目并确认入库" if needs_project else "确认知晓告警并入库"
        actions.append({"id": "ack_and_confirm", "label": label})
    if batch.status == "confirmed":
        actions.append({"id": "show_summary", "label": "查看汇总"})
    return {
        "type": "staffing_batch",
        "batch_id": batch.id,
        "filename": batch.filename,
        "status": batch.status,
        "project_id": batch.project_id,
        "needs_project": needs_project,
        "match_status": match_status,
        "match_codes": list(match_info.get("codes_tried") or []),
        "project_candidates": candidates,
        "collisions": collisions,
        "roster_unresolved": roster_unresolved,
        "roster_unavailable": roster_unavailable,
        "warning_count": len(warnings),
        "warnings": warnings[:30],
        "note": auto_note,
        "actions": actions,
    }


async def handle_staffing_message(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
    message: str,
    attachment: dict[str, Any] | None,
    auto_note: str | None = None,
) -> dict[str, Any]:
    """Handle a user chat turn claimed by staffing. Returns text + optional card."""
    ensure_tool_allowed(principal, TOOL_STAFFING)
    state = _tool_state(conversation)
    staffing = dict(state.get("staffing") or {})

    # Affirm after clarify
    text = (message or "").strip()

    if attachment:
        data = attachment["data"]
        filename = attachment["filename"]
        batch_id = new_id()
        storage = FileDocumentStorage(get_settings().document_storage_dir)
        storage_key = storage.store_staffing(batch_id, filename, data)
        batch = await staffing_service.create_import_batch(
            session,
            principal=principal,
            filename=filename,
            data=data,
            storage_key=storage_key,
            batch_id=batch_id,
        )
        update_staffing_state(
            conversation,
            batch_id=batch.id,
            project_id=batch.project_id,
        )
        note = auto_note or "已按人员投入处理该表格。"
        card = _batch_card(batch, auto_note=note)
        warn_n = len(batch.warnings or [])
        if card.get("needs_project"):
            codes = "、".join(card.get("match_codes") or []) or "（未能解析项目码）"
            body = (
                f"{note}\n"
                f"文件：{batch.filename}；状态：{batch.status}；告警 {warn_n} 条。\n"
                f"未能自动匹配项目（文件码：{codes}）。请在下方选定项目后再确认入库。"
            )
        else:
            body = (
                f"{note}\n"
                f"文件：{batch.filename}；状态：{batch.status}；告警 {warn_n} 条。\n"
                "如需入库，请点击下方确认。"
            )
        return {"content": body, "card": card}

    # Query summary without new file
    project_id = staffing.get("project_id")
    if re_query_summary(text) and project_id:
        summary = await staffing_service.project_summary(
            session, principal=principal, project_id=project_id
        )
        card = _summary_card(summary)
        lines = [f"项目汇总（{card['label']}）：内部员工 {card['person_count']} 人"]
        for p in card["people"][:40]:
            lines.append(f"- {p['person_name']} · {p['person_kind_label']} · {p['days_on_site']} 天")
        return {"content": "\n".join(lines), "card": card}

    if re_confirm(text):
        raise AppError("请使用确认按钮完成入库（防止误操作）", status_code=400)

    if not attachment:
        return {
            "content": (
                "人员投入助手已就绪。请上传项目日报（Excel .xlsx，或由该工作簿导出的 PDF），"
                "或询问当前已绑定项目的「有谁 / 各几天」。"
            ),
            "card": None,
        }

    return {"content": "未能处理该请求。", "card": None}


def re_query_summary(text: str) -> bool:
    import re

    return bool(re.search(r"(有谁|多少人|汇总|在场|人天|几天)", text or ""))


def re_confirm(text: str) -> bool:
    import re

    return bool(re.search(r"确认入库", text or ""))


async def apply_tool_action(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Button-driven actions that mutate staffing state. Requires explicit action id."""
    ensure_tool_allowed(principal, TOOL_STAFFING)
    payload = payload or {}
    state = _tool_state(conversation)
    staffing = dict(state.get("staffing") or {})
    batch_id = payload.get("batch_id") or staffing.get("batch_id")
    project_id = payload.get("project_id") or staffing.get("project_id")

    if action == "ack_and_confirm":
        if not can_use_staffing(principal, write=True):
            raise AppError("需要人员投入写入权限或不在项目管理部组织范围", status_code=403)
        if not batch_id:
            raise AppError("没有可确认的导入批次", status_code=400)
        batch = await staffing_service.get_batch(session, principal.tenant_id, batch_id)
        bind_project_id = project_id or batch.project_id
        if not bind_project_id:
            raise AppError("请先选定项目后再确认入库", status_code=400)
        if batch.status == "needs_review":
            skip_ack = {
                "name_kind_collision",
                "roster_name_unresolved",
                "roster_unavailable",
                "roster_name_corrected",
            }
            resolutions: dict[str, Any] = {}
            for w in batch.warnings or []:
                if not isinstance(w, dict) or not w.get("code"):
                    continue
                code = w["code"]
                if code in skip_ack:
                    continue
                resolutions[code] = "acknowledged"
            collision_payload = payload.get("name_kind_collision")
            if isinstance(collision_payload, dict):
                resolutions["name_kind_collision"] = collision_payload
            elif any(
                isinstance(w, dict) and w.get("code") == "name_kind_collision"
                for w in (batch.warnings or [])
            ):
                raise AppError("请先裁定同名双身份（分列或合并）", status_code=400)
            roster_payload = payload.get("roster_name_unresolved")
            if isinstance(roster_payload, dict):
                resolutions["roster_name_unresolved"] = roster_payload
            elif any(
                isinstance(w, dict) and w.get("code") == "roster_name_unresolved"
                for w in (batch.warnings or [])
            ):
                raise AppError("请先裁定花名册无法确认的姓名", status_code=400)
            if any(
                isinstance(w, dict) and w.get("code") == "roster_unavailable"
                for w in (batch.warnings or [])
            ):
                raise AppError(
                    "人员信息花名册不可用，请配置后重新导入",
                    status_code=400,
                )
            batch = await staffing_service.review_batch(
                session,
                principal=principal,
                batch_id=batch_id,
                project_id=bind_project_id,
                resolutions=resolutions,
            )
        batch = await staffing_service.confirm_batch(
            session, principal=principal, batch_id=batch.id
        )
        update_staffing_state(
            conversation, batch_id=batch.id, project_id=batch.project_id
        )
        if not batch.project_id:
            return {
                "content": "已确认批次，但尚未绑定项目，无法汇总。",
                "card": _batch_card(batch),
            }
        summary = await staffing_service.project_summary(
            session, principal=principal, project_id=batch.project_id
        )
        card = _summary_card(summary)
        title = f"{card.get('project_code') or ''} {card.get('project_name') or ''}".strip()
        return {
            "content": (
                f"已确认入库{(' · ' + title) if title else ''}。"
                f"内部员工 {card['person_count']} 人，人天 {card.get('person_day_total') or 0}。"
            ),
            "card": card,
        }

    if action == "void_person":
        if not can_use_staffing(principal, write=True):
            raise AppError("需要人员投入写入权限或不在项目管理部组织范围", status_code=403)
        if not project_id:
            raise AppError("缺少项目", status_code=400)
        names = payload.get("person_names") or []
        if not names:
            raise AppError("请指定要作废的人员", status_code=400)
        # Require explicit confirm flag from UI second step
        if not payload.get("confirmed"):
            raise AppError("作废需要二次确认", status_code=400)
        count = await staffing_service.void_facts(
            session,
            principal=principal,
            project_id=project_id,
            scope="person",
            person_names=list(names),
        )
        summary = await staffing_service.project_summary(
            session, principal=principal, project_id=project_id
        )
        return {
            "content": f"已作废 {count} 条在场记录。",
            "card": _summary_card(summary),
        }

    if action == "show_summary":
        if not project_id:
            raise AppError("缺少项目", status_code=400)
        summary = await staffing_service.project_summary(
            session, principal=principal, project_id=project_id
        )
        return {"content": "当前项目汇总如下。", "card": _summary_card(summary)}

    raise AppError(f"未知工具动作: {action}", status_code=400)
