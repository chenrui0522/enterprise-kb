## 1. Tool registry and routing

- [x] 1.1 Add server-side tool registry (staffing first) with required permissions and verify a unit test denies invoke without `staffing:read|write`
- [x] 1.2 Implement M3 turn router (explicit tool > strong rules > weak clarify > RAG) with fixed Chinese copy for weak clarify; verify unit tests cover strong/weak/none fixtures
- [x] 1.3 Persist conversation tool state (`active_tool`, staffing `batch_id`/`project_id`) and verify it clears on new conversation

## 2. Chat attachments and staffing orchestrator

- [x] 2.1 Add chat attachment upload API accepting `.xlsx` into existing storage and verify unauthorized users get 401/403
- [x] 2.2 Wire staffing orchestrator to existing import/review/confirm/summary/void services and verify import-then-confirm produces summary for an authorized project in API tests
- [x] 2.3 Require explicit tool_action confirmation for confirm-import and void; verify without confirmation facts are unchanged

## 3. Composer UX

- [x] 3.1 Add composer tool dropdown filtered by permissions at the send-button adjacent control; verify no staffing item when user lacks staffing perms
- [x] 3.2 Add xlsx attach control and show selected filename in composer; verify send includes attachment id/metadata
- [x] 3.3 Render staffing cards (warnings, summary table, confirm/void buttons) in the message list and verify clicking confirm calls tool_action API

## 4. Knowledge-qa guard + page keep

- [x] 4.1 When staffing claims the turn, skip RAG factual answer for headcount/days and verify test asserts response uses staffing summary path
- [x] 4.2 Confirm `/staffing` route and nav entry still work; verify smoke open page still lists projects / upload UI

## 5. Docs and regression

- [x] 5.1 Update README briefly: chat tool dropdown + staffing-in-chat; verify wording matches P1 (page kept)
- [x] 5.2 Run staffing + chat related pytest and verify green
