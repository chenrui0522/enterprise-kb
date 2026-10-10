"""Leave-ledger workflow orchestration from chat turns."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tools.attachments import load_attachment, save_chat_xlsx
from app.chat.tools.leave_ledger_query import answer_leave_query
from app.chat.tools.registry import TOOL_LEAVE_LEDGER, ensure_tool_allowed
from app.core.config import get_settings
from app.core.errors import AppError
from app.identity.feature_gates import can_use_leave_ledger
from app.identity.principal import Principal
from app.ingestion.storage import FileDocumentStorage
from app.leave_ledger.classify import ROLES, classify_source
from app.leave_ledger.import_export import looks_like_official_export
from app.leave_ledger import service as leave_service
from app.leave_ledger.service import ROLE_LABEL
from app.models.entity import Conversation

_ROLE_REPLY = {
    "出差": "travel",
    "出差申请": "travel",
    "travel": "travel",
    "加班": "overtime",
    "加班申请": "overtime",
    "overtime": "overtime",
    "请假": "leave",
    "请假申请": "leave",
    "leave": "leave",
    "打卡": "punch",
    "打卡日报": "punch",
    "punch": "punch",
}


def _tool_state(conversation: Conversation) -> dict[str, Any]:
    raw = conversation.tool_state
    return dict(raw) if isinstance(raw, dict) else {}


def update_leave_ledger_state(
    conversation: Conversation,
    *,
    active_tool: str | None = TOOL_LEAVE_LEDGER,
    job_id: str | None = None,
    pending_attachment: dict[str, Any] | None = None,
    pending_prior: dict[str, Any] | None = None,
    last_person_name: str | None = None,
    clear_pending: bool = False,
    clear_pending_prior: bool = False,
) -> None:
    state = _tool_state(conversation)
    if active_tool:
        state["active_tool"] = active_tool
    leave = dict(state.get("leave_ledger") or {})
    if job_id is not None:
        leave["job_id"] = job_id
    if clear_pending:
        leave.pop("pending_attachment", None)
    elif pending_attachment is not None:
        leave["pending_attachment"] = pending_attachment
    if clear_pending_prior:
        leave.pop("pending_prior", None)
    elif pending_prior is not None:
        leave["pending_prior"] = pending_prior
    if last_person_name is not None:
        leave["last_person_name"] = last_person_name
    state["leave_ledger"] = leave
    conversation.tool_state = state


def _storage() -> FileDocumentStorage:
    return FileDocumentStorage(get_settings().document_storage_dir)


def try_classify_role(filename: str, data: bytes) -> str | None:
    try:
        return classify_source(filename, data)
    except AppError as exc:
        if "无法识别" in (exc.message or "") or "角色" in (exc.message or ""):
            return None
        raise


def parse_role_reply(message: str) -> str | None:
    text = (message or "").strip().lower()
    if not text:
        return None
    for key, role in _ROLE_REPLY.items():
        if text == key.lower() or text.startswith(key.lower()):
            return role
    return None


async def _progress_card(
    session: AsyncSession,
    job,
    *,
    note: str | None = None,
    need_role_pick: bool = False,
    pending_filename: str | None = None,
    pending_prior_filename: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    sources = await leave_service.list_sources(session, job.id)
    present = {s.role: s.filename for s in sources}
    roles = []
    for role in ROLES:
        roles.append(
            {
                "role": role,
                "label": ROLE_LABEL.get(role, role),
                "filled": role in present,
                "filename": present.get(role),
            }
        )
    prior_options: list[dict[str, Any]] = []
    tid = tenant_id or job.tenant_id
    if job.status not in ("confirmed", "voided") and (job.compute_result or {}).get(
        "rows"
    ):
        for pj in await leave_service.list_confirmed_jobs(session, tenant_id=tid):
            if pj.id == job.id:
                continue
            prow = (pj.compute_result or {}).get("rows") or []
            prior_options.append(
                {
                    "id": pj.id,
                    "person_count": len(prow),
                    "confirmed_at": (
                        pj.confirmed_at.isoformat() if pj.confirmed_at else None
                    ),
                    "prior_source": leave_service.prior_source_of_job(pj),
                }
            )
    def _warn_payload(w: dict) -> dict:
        return {
            "code": w.get("code"),
            "message": w.get("message"),
            "blocking": w.get("blocking", True),
            "detail": w.get("detail") if isinstance(w.get("detail"), dict) else {},
        }

    all_warnings = [
        _warn_payload(w) for w in (job.warnings or []) if isinstance(w, dict)
    ]
    missing = [r for r in roles if not r["filled"]]
    open_blocking = leave_service._open_blocking_warnings(
        job.warnings, job.resolved_warnings
    )
    # Prefer unresolved blocking warnings so the chat card never hides them
    # behind a non-blocking / already-resolved prefix slice.
    open_blocking_payload = [_warn_payload(w) for w in open_blocking]
    open_ids = {id(w) for w in open_blocking}
    other_warnings = [
        _warn_payload(w)
        for w in (job.warnings or [])
        if isinstance(w, dict) and id(w) not in open_ids
    ]
    warnings_for_card = (open_blocking_payload + other_warnings)[:200]
    actions: list[dict[str, str]] = []
    if need_role_pick:
        for role in ROLES:
            actions.append(
                {
                    "id": f"leave_ledger.pick_role:{role}",
                    "label": ROLE_LABEL.get(role, role),
                }
            )
    else:
        if job.status in ("needs_review", "parsed", "collecting") and missing:
            for m in missing:
                actions.append(
                    {
                        "id": f"leave_ledger.accept_missing:{m['role']}",
                        "label": f"接受缺失·{m['label']}",
                    }
                )
        if job.status == "needs_review" and open_blocking:
            actions.append({"id": "leave_ledger.review", "label": "提交复核决议"})
        if (
            job.status in ("parsed", "needs_review")
            and (job.compute_result or {}).get("rows")
        ):
            actions.append({"id": "leave_ledger.merge", "label": "合并所选 prior"})
        if pending_prior_filename:
            actions.append(
                {
                    "id": "leave_ledger.confirm_prior_merge",
                    "label": "用上传台账合并",
                }
            )
            actions.append(
                {"id": "leave_ledger.dismiss_prior", "label": "取消上传台账"}
            )
        if job.status in ("parsed", "needs_review") and not open_blocking:
            actions.append({"id": "leave_ledger.confirm", "label": "确认台账"})
        if job.status == "confirmed":
            actions.append({"id": "leave_ledger.export", "label": "导出 Excel"})
        if job.status not in ("voided",):
            actions.append({"id": "leave_ledger.void", "label": "作废任务"})

    return {
        "type": "leave_ledger_job",
        "job_id": job.id,
        "status": job.status,
        "roles": roles,
        "missing_roles": [m["role"] for m in missing],
        "warning_count": len(all_warnings),
        "warnings": warnings_for_card,
        "resolved_warnings": job.resolved_warnings or {},
        "open_blocking_count": len(open_blocking),
        "row_count": len((job.compute_result or {}).get("rows") or []),
        "need_role_pick": need_role_pick,
        "pending_filename": pending_filename,
        "pending_prior_filename": pending_prior_filename,
        "prior_options": prior_options,
        "merged_from_job_id": (job.compute_result or {}).get("merged_from_job_id"),
        "note": note,
        "actions": actions,
    }


async def _ensure_job(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
) -> Any:
    state = _tool_state(conversation)
    leave = dict(state.get("leave_ledger") or {})
    job_id = leave.get("job_id")
    if job_id:
        return await leave_service.get_job(session, principal.tenant_id, job_id)
    job = await leave_service.create_empty_job(session, principal=principal)
    update_leave_ledger_state(conversation, job_id=job.id)
    return job


async def _add_attachment_with_role(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
    job,
    filename: str,
    data: bytes,
    role: str | None,
    auto_note: str | None,
) -> dict[str, Any]:
    if role is None:
        role = try_classify_role(filename, data)
    if role is None:
        # Persist pending bytes under chat attachments for later pick_role.
        meta = save_chat_xlsx(user_id=principal.user_id, filename=filename, data=data)
        update_leave_ledger_state(
            conversation,
            job_id=job.id,
            pending_attachment={
                "id": meta["id"],
                "filename": meta["filename"],
                "storage_key": meta["storage_key"],
            },
        )
        card = await _progress_card(
            session,
            job,
            note=auto_note,
            need_role_pick=True,
            pending_filename=filename,
        )
        return {
            "content": (
                f"{(auto_note + '\n') if auto_note else ''}"
                f"无法自动判定「{filename}」属于哪一类来源。"
                "请选择：出差申请 / 加班申请 / 请假申请 / 打卡日报。"
            ),
            "card": card,
        }

    job = await leave_service.add_source_file(
        session,
        principal=principal,
        job_id=job.id,
        filename=filename,
        data=data,
        storage=_storage(),
        role=role,
    )
    update_leave_ledger_state(
        conversation, job_id=job.id, clear_pending=True
    )
    card = await _progress_card(session, job, note=auto_note)
    filled = sum(1 for r in card["roles"] if r["filled"])
    missing_labels = "、".join(
        ROLE_LABEL.get(r, r) for r in card["missing_roles"]
    ) or "无"
    note = auto_note or "已按调休台账处理该表格。"
    body = (
        f"{note}\n"
        f"已收录 {ROLE_LABEL.get(role, role)}（{filename}）。"
        f"进度 {filled}/4；仍缺：{missing_labels}。"
        f"状态：{job.status}；告警 {card['warning_count']} 条。"
    )
    return {"content": body, "card": card}


async def handle_leave_ledger_message(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
    message: str,
    attachment: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    auto_note: str | None = None,
) -> dict[str, Any]:
    """Handle a user chat turn claimed by leave_ledger. Returns text + optional card."""
    ensure_tool_allowed(principal, TOOL_LEAVE_LEDGER)
    text = (message or "").strip()
    state = _tool_state(conversation)
    leave = dict(state.get("leave_ledger") or {})
    pending = leave.get("pending_attachment")
    batch = [a for a in (attachments or []) if a and a.get("filename") and a.get("data") is not None]
    if not batch and attachment:
        batch = [attachment]

    if re_confirm(text):
        raise AppError("请使用确认按钮完成台账确认（防止误操作）", status_code=400)

    # Role reply while a pending attachment awaits classification.
    if pending and not batch:
        role = parse_role_reply(text)
        if role:
            loaded = load_attachment(pending["id"], user_id=principal.user_id)
            job = await _ensure_job(
                session, principal=principal, conversation=conversation
            )
            return await _add_attachment_with_role(
                session,
                principal=principal,
                conversation=conversation,
                job=job,
                filename=loaded["filename"],
                data=loaded["data"],
                role=role,
                auto_note=auto_note,
            )
        card_job = None
        if leave.get("job_id"):
            card_job = await leave_service.get_job(
                session, principal.tenant_id, leave["job_id"]
            )
            card = await _progress_card(
                session,
                card_job,
                need_role_pick=True,
                pending_filename=pending.get("filename"),
            )
        else:
            card = None
        return {
            "content": (
                f"仍无法判定「{pending.get('filename') or '附件'}」的角色。"
                "请回复出差/加班/请假/打卡，或点击下方按钮。"
            ),
            "card": card,
        }

    if batch:
        return await _handle_attachment_batch(
            session,
            principal=principal,
            conversation=conversation,
            batch=batch,
            auto_note=auto_note,
        )

    job_id = leave.get("job_id")
    if job_id:
        job = await leave_service.get_job(session, principal.tenant_id, job_id)
        pending_prior = leave.get("pending_prior") or {}
        card = await _progress_card(
            session,
            job,
            pending_prior_filename=pending_prior.get("filename"),
        )
        rows = list((job.compute_result or {}).get("rows") or [])
        totals = (job.compute_result or {}).get("totals")
        if not isinstance(totals, dict):
            totals = None
        answered, sticky_person = answer_leave_query(
            text,
            rows=rows,
            job_status=job.status,
            warning_count=int(card.get("warning_count") or 0),
            open_blocking=int(card.get("open_blocking_count") or 0),
            totals=totals,
            prior_option_count=len(card.get("prior_options") or []),
            last_person_name=leave.get("last_person_name"),
        )
        if answered is not None:
            if sticky_person:
                update_leave_ledger_state(
                    conversation, job_id=job.id, last_person_name=sticky_person
                )
            return {"content": answered, "card": card}
        if job.status == "confirmed":
            tip = (
                "当前调休台账已确认。可导出 Excel，或询问结果（如「张三剩余调休」「多少人」）。"
                "若要合并上月/上一版：须在确认前操作——请作废重做或新建本月任务后再合并。"
            )
        else:
            tip = (
                "调休台账任务进行中。"
                "可询问当前结果（如「张三剩余调休」「多少人/汇总」）；"
                "或继续上传出差/加班/请假/打卡来源（xlsx），"
                "可一次多选或分次上传；"
                "也可上传本系统导出的上月台账或在卡片中选择 prior 合并；"
                "或在下方卡片中接受缺失、复核告警后确认导出。"
            )
        return {"content": tip, "card": card}

    answered_no_job, _ = answer_leave_query(
        text,
        rows=[],
        job_status="none",
        warning_count=0,
        open_blocking=0,
    )
    if answered_no_job is not None:
        return {
            "content": (
                "当前会话还没有调休台账计算结果。"
                "请先上传出差/加班/请假/打卡来源（xlsx）并完成计算后再提问。"
            ),
            "card": None,
        }

    return {
        "content": (
            "调休台账助手已就绪。请上传出差申请、法定假日加班申请、"
            "请假申请与打卡日报（Excel .xlsx），可一次多选或分次上传；"
            "缺一类可在复核时接受缺失。算出结果后可直接问某人额度或「多少人」。"
        ),
        "card": None,
    }


async def _handle_export_prior_upload(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
    filename: str,
    data: bytes,
    leftover_names: list[str],
    auto_note: str | None,
) -> dict[str, Any]:
    """Hold official export as pending prior; do not fill four-source slots."""
    job = await _ensure_job(session, principal=principal, conversation=conversation)
    rows = list((job.compute_result or {}).get("rows") or [])
    if job.status in ("confirmed", "voided") or not rows:
        return {
            "content": (
                f"识别到正式导出台账「{filename}」，但当前任务尚无计算结果或已确认/作废，"
                "无法合并。请先完成本月四源计算后再上传 prior 台账。"
            ),
            "card": await _progress_card(session, job, note=auto_note),
        }
    meta = save_chat_xlsx(user_id=principal.user_id, filename=filename, data=data)
    update_leave_ledger_state(
        conversation,
        job_id=job.id,
        pending_prior={
            "id": meta["id"],
            "filename": meta["filename"],
            "storage_key": meta["storage_key"],
        },
    )
    card = await _progress_card(
        session,
        job,
        note=auto_note,
        pending_prior_filename=meta["filename"],
    )
    lines = [
        f"识别到本系统正式导出台账「{filename}」，未计入四源槽位。",
        "请确认是否用其作为 prior 合并到当前任务（点「用上传台账合并」）。",
    ]
    if leftover_names:
        lines.append(
            "本轮其余附件未处理，请确认 prior 后再单独上传："
            + "、".join(leftover_names)
            + "。"
        )
    content = ("\n".join(lines))
    if auto_note:
        content = f"{auto_note}\n{content}"
    return {"content": content, "card": card}


async def _handle_attachment_batch(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
    batch: list[dict[str, Any]],
    auto_note: str | None,
) -> dict[str, Any]:
    """Add auto-classified sources in order; stop at first ambiguous role."""
    export_indexes = [
        i
        for i, item in enumerate(batch)
        if looks_like_official_export(item.get("data") or b"")
    ]
    if export_indexes:
        idx = export_indexes[0]
        item = batch[idx]
        leftover = [
            str(a.get("filename") or "附件")
            for i, a in enumerate(batch)
            if i != idx
        ]
        return await _handle_export_prior_upload(
            session,
            principal=principal,
            conversation=conversation,
            filename=str(item.get("filename") or "导出台账.xlsx"),
            data=item["data"],
            leftover_names=leftover,
            auto_note=auto_note,
        )

    job = await _ensure_job(session, principal=principal, conversation=conversation)
    added: list[str] = []
    dup_errors: list[str] = []
    for index, item in enumerate(batch):
        filename = str(item.get("filename") or "附件")
        data = item["data"]
        role = try_classify_role(filename, data)
        if role is None:
            leftover = [str(a.get("filename") or "附件") for a in batch[index + 1 :]]
            result = await _add_attachment_with_role(
                session,
                principal=principal,
                conversation=conversation,
                job=job,
                filename=filename,
                data=data,
                role=None,
                auto_note=auto_note,
            )
            parts = [result["content"]]
            if added:
                parts.append("本轮已收录：" + "；".join(added) + "。")
            if leftover:
                parts.append(
                    "以下文件尚未处理，请指定角色后或重新附上："
                    + "、".join(leftover)
                    + "。"
                )
            result["content"] = "\n".join(parts)
            return result

        try:
            job = await leave_service.add_source_file(
                session,
                principal=principal,
                job_id=job.id,
                filename=filename,
                data=data,
                storage=_storage(),
                role=role,
            )
        except AppError as exc:
            msg = exc.message or str(exc)
            if "已有" in msg or "重复" in msg:
                dup_errors.append(f"{filename}（{ROLE_LABEL.get(role, role)}）：{msg}")
                continue
            raise
        update_leave_ledger_state(conversation, job_id=job.id, clear_pending=True)
        added.append(f"{ROLE_LABEL.get(role, role)}（{filename}）")

    card = await _progress_card(session, job, note=auto_note)
    filled = sum(1 for r in card["roles"] if r["filled"])
    missing_labels = "、".join(
        ROLE_LABEL.get(r, r) for r in card["missing_roles"]
    ) or "无"
    note = auto_note or "已按调休台账处理。"
    lines = [
        note,
        f"本轮已收录 {len(added)} 份：" + ("；".join(added) if added else "无") + "。",
        f"进度 {filled}/4；仍缺：{missing_labels}。状态：{job.status}；告警 {card['warning_count']} 条。",
    ]
    if dup_errors:
        lines.append("未写入（角色重复）：" + "；".join(dup_errors))
    return {"content": "\n".join(lines), "card": card}


def re_confirm(text: str) -> bool:
    return bool(re.search(r"(确认台账|确认调休)", text or ""))


async def apply_leave_ledger_action(
    session: AsyncSession,
    *,
    principal: Principal,
    conversation: Conversation,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Button-driven leave-ledger actions. Requires explicit action id."""
    ensure_tool_allowed(principal, TOOL_LEAVE_LEDGER)
    payload = payload or {}
    state = _tool_state(conversation)
    leave = dict(state.get("leave_ledger") or {})
    job_id = payload.get("job_id") or leave.get("job_id")

    # Normalize namespaced / compound actions
    role_pick: str | None = None
    accept_role: str | None = None
    if action.startswith("leave_ledger.pick_role:"):
        role_pick = action.split(":", 1)[1]
        action = "leave_ledger.pick_role"
    elif action.startswith("leave_ledger.accept_missing:"):
        accept_role = action.split(":", 1)[1]
        action = "leave_ledger.accept_missing"
    elif action == "pick_role":
        action = "leave_ledger.pick_role"
        role_pick = payload.get("role")
    elif action == "accept_missing":
        action = "leave_ledger.accept_missing"
        accept_role = payload.get("role")
    elif not action.startswith("leave_ledger."):
        action = f"leave_ledger.{action}"

    if action == "leave_ledger.pick_role":
        role = role_pick or payload.get("role")
        if role not in ROLES:
            raise AppError("请指定有效来源角色", status_code=400)
        pending = leave.get("pending_attachment")
        if not pending:
            raise AppError("没有待指定角色的附件", status_code=400)
        if not can_use_leave_ledger(principal, write=True):
            raise AppError("需要调休台账写入权限或不在运营管理中心组织范围", status_code=403)
        loaded = load_attachment(pending["id"], user_id=principal.user_id)
        job = await _ensure_job(session, principal=principal, conversation=conversation)
        return await _add_attachment_with_role(
            session,
            principal=principal,
            conversation=conversation,
            job=job,
            filename=loaded["filename"],
            data=loaded["data"],
            role=role,
            auto_note=None,
        )

    if not job_id:
        raise AppError("没有可操作的调休台账任务", status_code=400)

    if action == "leave_ledger.accept_missing":
        if not can_use_leave_ledger(principal, write=True):
            raise AppError("需要调休台账写入权限或不在运营管理中心组织范围", status_code=403)
        role = accept_role or payload.get("role")
        if role not in ROLES:
            raise AppError("请指定要接受缺失的角色", status_code=400)
        job = await leave_service.review_job(
            session,
            principal=principal,
            job_id=job_id,
            resolutions={"missing_sources": {role: "accept"}},
            storage=_storage(),
        )
        update_leave_ledger_state(conversation, job_id=job.id)
        card = await _progress_card(session, job)
        return {
            "content": f"已接受缺失「{ROLE_LABEL.get(role, role)}」。",
            "card": card,
        }

    if action == "leave_ledger.review":
        if not can_use_leave_ledger(principal, write=True):
            raise AppError("需要调休台账写入权限或不在运营管理中心组织范围", status_code=403)
        resolutions = payload.get("resolutions") or {}
        if not isinstance(resolutions, dict):
            raise AppError("复核决议格式无效", status_code=400)
        job = await leave_service.review_job(
            session,
            principal=principal,
            job_id=job_id,
            resolutions=resolutions,
            storage=_storage(),
        )
        update_leave_ledger_state(conversation, job_id=job.id)
        card = await _progress_card(session, job)
        return {"content": "已提交复核决议。", "card": card}

    if action == "leave_ledger.merge":
        if not can_use_leave_ledger(principal, write=True):
            raise AppError("需要调休台账写入权限或不在运营管理中心组织范围", status_code=403)
        prior_job_id = str(payload.get("prior_job_id") or "").strip()
        if not prior_job_id:
            raise AppError("请选择 prior 台账任务后再合并", status_code=400)
        job = await leave_service.merge_job(
            session,
            principal=principal,
            job_id=job_id,
            prior_job_id=prior_job_id,
        )
        update_leave_ledger_state(conversation, job_id=job.id, clear_pending_prior=True)
        card = await _progress_card(session, job)
        return {
            "content": (
                f"已合并 prior（{prior_job_id[:8]}…）到当前任务，"
                f"现共 {card['row_count']} 人。请继续复核后确认。"
            ),
            "card": card,
        }

    if action == "leave_ledger.confirm_prior_merge":
        if not can_use_leave_ledger(principal, write=True):
            raise AppError("需要调休台账写入权限或不在运营管理中心组织范围", status_code=403)
        pending_prior = leave.get("pending_prior")
        if not pending_prior:
            raise AppError("没有待合并的上传台账", status_code=400)
        loaded = load_attachment(pending_prior["id"], user_id=principal.user_id)
        prior = await leave_service.import_prior_from_export(
            session,
            principal=principal,
            filename=loaded["filename"],
            data=loaded["data"],
        )
        job = await leave_service.merge_job(
            session,
            principal=principal,
            job_id=job_id,
            prior_job_id=prior.id,
        )
        update_leave_ledger_state(conversation, job_id=job.id, clear_pending_prior=True)
        card = await _progress_card(session, job)
        return {
            "content": (
                f"已导入「{loaded['filename']}」为 prior 并合并到当前任务，"
                f"现共 {card['row_count']} 人。请继续复核后确认。"
            ),
            "card": card,
        }

    if action == "leave_ledger.dismiss_prior":
        update_leave_ledger_state(conversation, clear_pending_prior=True)
        job = await leave_service.get_job(session, principal.tenant_id, job_id)
        card = await _progress_card(session, job)
        return {"content": "已取消待合并的上传台账。", "card": card}

    if action == "leave_ledger.confirm":
        if not can_use_leave_ledger(principal, write=True):
            raise AppError("需要调休台账写入权限或不在运营管理中心组织范围", status_code=403)
        if not payload.get("confirmed"):
            raise AppError("确认台账需要二次确认", status_code=400)
        resolutions = payload.get("resolutions")
        if isinstance(resolutions, dict) and resolutions:
            await leave_service.review_job(
                session,
                principal=principal,
                job_id=job_id,
                resolutions=resolutions,
                storage=_storage(),
            )
        job = await leave_service.confirm_job(
            session, principal=principal, job_id=job_id
        )
        update_leave_ledger_state(conversation, job_id=job.id)
        card = await _progress_card(session, job)
        return {
            "content": f"已确认调休台账，共 {card['row_count']} 人。可导出 Excel。",
            "card": card,
        }

    if action == "leave_ledger.export":
        job = await leave_service.get_job(session, principal.tenant_id, job_id)
        if job.status != "confirmed":
            raise AppError("仅已确认任务可导出正式台账", status_code=400)
        # Bytes via REST; card signals frontend to download.
        card = await _progress_card(session, job)
        card["export_ready"] = True
        card["export_path"] = f"/api/v1/leave-ledger/jobs/{job.id}/export.xlsx"
        return {
            "content": "台账已确认，请下载下方导出的 Excel。",
            "card": card,
            "export_job_id": job.id,
        }

    if action == "leave_ledger.void":
        if not can_use_leave_ledger(principal, write=True):
            raise AppError("需要调休台账写入权限或不在运营管理中心组织范围", status_code=403)
        if not payload.get("confirmed"):
            raise AppError("作废需要二次确认", status_code=400)
        job = await leave_service.void_job(
            session,
            principal=principal,
            job_id=job_id,
            reason=payload.get("reason") or "对话中作废",
        )
        update_leave_ledger_state(conversation, job_id=job.id)
        card = await _progress_card(session, job)
        return {"content": "已作废该调休台账任务。", "card": card}

    raise AppError(f"未知工具动作: {action}", status_code=400)
