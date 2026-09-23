## 1. Data model

- [x] 1.1 Add `conversations.title_source` (`default` | `auto` | `user`) + Alembic migration; verify migrate applies and existing rows backfill (「新对话」→ default, else → user)
- [x] 1.2 Expose `title_source` on conversation schemas/API out models; verify list/get include the field

## 2. Rule title + stream

- [x] 2.1 Implement `derive_rule_title(message, filename)` with unit tests (text, filename-only, truncate, whitespace)
- [x] 2.2 On chat stream (and inline create), when `title_source == default`, set rule title + `auto`; verify first message renames「新对话」and second message does not overwrite `auto`/`user`

## 3. Async polish

- [x] 3.1 Enqueue title-polish job after rule naming; verify job payload and that chat response is not blocked
- [x] 3.2 Worker: LLM short title + write only if `title_source == auto`; verify success replaces title, user PATCH wins race, failure keeps rule title

## 4. Manual rename

- [x] 4.1 `PATCH /conversations/{id}` with title validation; verify empty rejected and `title_source` becomes `user`
- [x] 4.2 ChatPage sidebar/header inline edit + refresh after send; verify rename persists and list updates; after first send list shows rule title

## 5. Backfill and docs

- [x] 5.1 Optional backfill for default-titled conversations that already have user messages (rule only); verify sample rows update
- [x] 5.2 README brief note on auto title + rename; verify related pytest green
