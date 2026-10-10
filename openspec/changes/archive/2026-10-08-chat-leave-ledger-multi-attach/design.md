## Context

See proposal.md - Why. Today:

- `ChatPage` keeps a single `attachment` and `files?.[0]`; no `multiple` on the file input.
- `ChatRequest.attachment_id` is singular; `_chat_event_stream_inner` loads one attachment into the leave-ledger / staffing tool path.
- `handle_leave_ledger_message` already does one `add_source` per turn; looping is natural once the turn carries N attachments.
- Upload endpoint `POST /chat/attachments` stays one-file-per-call (frontend uploads N times then sends).

## Goals / Non-Goals

**Goals:**

- Composer: multi-select, list of pending attachments, send with all of them.
- API: accept multiple attachment ids on one chat turn (backward compatible with `attachment_id`).
- Leave-ledger orchestrator: process the list in order on one claimed turn.
- Ambiguous role: first ambiguous file becomes `pending_attachment` (existing UX); already-classified files in that batch already committed.

**Non-Goals:**

- Batch upload API (multipart many files in one POST) — not required.
- Staffing / other tools consuming multiple attachments in one turn.
- Changing independent Leave Ledger page.
- Chat merge-prior UI in conversation (still page-centric).

## Decisions

1. **Additive `attachment_ids: list[str]` on `ChatRequest`**  
   Keep `attachment_id` for old clients. Effective list = `attachment_ids` if non-empty, else `[attachment_id]` if set, else `[]`. Cap length (e.g. 8) to bound abuse.  
   Alternative: only change frontend to send four sequential messages — worse UX, more race on job state.

2. **Frontend uploads sequentially then one send**  
   Reuse `uploadChatAttachment` per file; UI shows chip list; clear list after successful send.  
   Alternative: new multi-upload endpoint — extra surface, little gain.

3. **Leave-ledger only fully consumes the list**  
   When active/claimed tool is leave_ledger, process all ids. For other tools / plain RAG, use the first attachment only (and ignore the rest with a short note or silent drop — prefer short assistant note if extras present). Avoids staffing accidentally treating four ledgers as one batch.

4. **Ambiguity mid-batch**  
   Process in stable order (client list order). On first role-uncertain file: stop adding further files in that turn, set pending for that file, return progress card + role pick (same as today). Remaining unprocessed ids: either keep as additional pending queue in `tool_state.leave_ledger.pending_queue` **or** ask user to resend leftovers.  
   **Chosen:** `pending_queue` of remaining attachment metas after the ambiguous one, so user only picks roles; after each pick, drain queue automatically for auto-classifiable files until next ambiguous or empty. Simpler MVP alternative: stop and require user to resend remaining — worse UX. Prefer pending_queue if small; if too heavy for V1, stop-after-first-ambiguous and document that leftover files must be re-attached.  
   **V1 pick:** stop after first ambiguous; already-added files stay; message lists which filenames were not processed so user can re-attach. Avoids new queue state machine. Spec still satisfied (classified ones counted; ambiguous not counted).

5. **Duplicate role in one batch**  
   Existing `add_source_file` rejects duplicate role — surface error in assistant text for that file and continue others where possible, or fail the duplicate only.

## Risks / Trade-offs

- [Risk] Mid-batch ambiguous leaves user confused about which files landed → Mitigation: assistant summary listing added roles/filenames and skipped/pending names.
- [Risk] Non-leave tools with multi-select surprise → Mitigation: only leave_ledger loops; others first-only + hint.
- [Risk] Large N uploads timeout → Mitigation: cap count; sequential upload with busy state.

## Migration Plan

1. Deploy API accepting `attachment_ids` (ignore unknown field on old servers is N/A — ship together).
2. Deploy frontend multi-attach.
3. Update clerk guide. Rollback = revert FE/API; single `attachment_id` path remains.
