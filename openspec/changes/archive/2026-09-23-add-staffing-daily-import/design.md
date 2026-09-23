## Context

动机见 proposal.md。行为契约见 `specs/staffing-daily-import`、`specs/ops-observability`、`specs/identity-access` 增量。

既定事实：

- 底座已有组织/项目授权、`Principal`、JSON 运维日志（`log_event` / `timed_event`）、`write_audit` + Admin 审计页。
- 尚无 personnel/staffing 模块与相关表。
- 业务样表为「项目日报表」：多级合并表头；每日一行；内部员工线索在：
  - C 列「现场施工人员/人数」中的 `【公司人员】` 段；
  - 右侧分阶段「我司人员」姓名格（如机械安装下 K 列；表头为我司，可含外包性质用工的我司人员）。
- C 列 `【外包人员】` 为外部施工队，**本期不统计**。
- 原样 `2515项目日报260721.xlsx` 曾非标准封装；导入必须校验可解析 OOXML。

## Goals / Non-Goals

**Goals:**

- 导入日报即可得到项目维度「内部员工有谁 / 每人在场天数（不重复日历日）」；可区分正式我司与我司·外包性质。
- 脏数据与项目匹配歧义必须经人工复核后才能进入正式汇总。
- 出勤事实可软作废（日×人 / 按人全量 / 整批），重传按重叠日替换且可追溯。
- 关键路径运维可串、写操作可审计。

**Non-Goals:**

- 外部外包（有名/无名）投入统计与 Y/Z 决议。
- ERP 联动、计划窗驱动、计划对比。
- 把在场天数表述为「工时」。
- 新建独立日志/审计栈。

## Decisions

### D1 领域模型：导入批次 + 出勤事实

- **ImportBatch**：一次上传；状态 `parsed` | `needs_review` | `confirmed` | `voided`；保留原文件对象存储键、解析告警、匹配到的 `project_id`。
- **AttendanceFact**（原子单位）：`(tenant_id, project_id, work_date, person_name, person_kind, batch_id, status)`  
  - `person_kind`：`internal_formal`（正式我司，主来自 C【公司人员】）| `internal_contract`（我司·外包性质，主来自「我司人员」姓名格）  
  - `status`：`active` | `voided`  
  - 同一项目同一日同一人在 active 态至多一条（确认写入时按人去重；身份冲突用 D2 优先级）。
- **汇总**：只聚合 `active` 内部员工事实；在场天数 = 不重复 `work_date`；进场次数可派生为连续段数（只读）。

### D2 解析策略：内部员工双源并集

- 定位「日期」列、C 列「现场施工人员/人数」、各阶段「我司人员」姓名格（含 K 及电气等同类列）。
- 从 C 解析 `【公司人员】` 人名 → 默认 `internal_formal`。
- **忽略** C 中 `【外包人员】` 整段（有名与无名都不入库、不告警为须决议项）。
- 从「我司人员」姓名格解析顿号分隔人名 → 默认 `internal_contract`（业务确认：我司侧、可外包性质用工）。
- 当日内部员工 = 两源并集；同一人两源都出现时身份优先级：`internal_formal` > `internal_contract`。
- 两源名单严重不一致（例如姓名格有固定班组而 C 公司段长期为空且业务预期应一致）可打 `source_mismatch` 供复核，但不因存在外部外包文本而阻断。
- 同日多行：确认前按 `(date, person)` 去重。

替代：只信 C 或只信 K。放弃：样表显示内部员工分散在两处。

### D3 项目自动匹配（方案 2）

顺序：文件名抽连续数字项目号 → 标题单元格再抽 → 在用户已授权项目中精确或前缀匹配。

- 命中唯一：绑定 `project_id`（复核页仍可展示）。
- 0 或多条：`needs_review`，人工选定后才能确认。
- 未授权项目：拒绝确认。

### D4 复核闸门（无 Y/Z）

无告警且项目已唯一匹配时可一键确认；否则 `needs_review`。

默认告警（不少于）：

- `ambiguous_person_token`、`same_day_conflict`、`missing_date`、`project_unmatched` / `project_ambiguous`、`source_mismatch`、`unreadable_workbook`

有告警未全部决议前 MUST NOT 进入 `confirmed`。  
**不再**将无名外部外包列为须决议告警。

### D5 确认写入与重传重叠日替换

确认时在单事务内：

1. 计算本批次将写入的日期集合 D。  
2. 将该项目下日期 ∈ D 的既有 `active` 事实标为 `voided`（`superseded_by_batch`）。  
3. 插入本批次内部员工 `active` 事实。  
4. batch → `confirmed`；写审计与 ops。

非 D 内旧日保留。整批作废语义同前。

### D6 回退 P3

- 明细：`(date, person)` 交集作废。  
- 汇总：某人在本项目全部 `active` 作废。  
- 批次：该 batch 仍 `active` 的事实作废。  
软删 + `staffing.void.*` 审计。

### D7 观测与审计（复用底座）

运维：`staffing.import.parse` / `match_project` / `review.pending` / `import.confirm` / `void`。  
审计：`staffing.import`、`staffing.review.resolve`、`staffing.confirm`、`staffing.void.day|person|batch|day_person`。  
脱敏：不写日报全文；人员文本 `preview_text`。

### D8 API / 权限草图

- `POST /api/v1/staffing/imports`  
- `GET /api/v1/staffing/imports/{id}`  
- `POST .../review`、`.../confirm`  
- `GET .../projects/{project_id}/summary`（内部员工有谁/天数，可按 kind 分组）  
- `GET .../facts`、`POST .../void`  

权限：`staffing:read` + `staffing:write`（或拆 import/review/void），且须为项目成员。

### D9 前端最小面

「人员投入」：上传 → 复核 → 确认 → 汇总/明细（正式我司 / 我司·外包性质）；作废三入口。文案「在场天数」，禁「工时」。

## Risks / Trade-offs

- [姓名格日日重复导致天数偏大] → 产品已确认按格计在场；复核可作废异常人/日。  
- [「王磊工」等后缀] → `ambiguous_person_token`。  
- [表头「我司」与外包性质认知] → kind 用 `internal_contract` 表达，不与外部外包混名。  
- [非标准 xlsx] → 校验拒收。  

## Migration Plan

1. Alembic：batches、facts。  
2. 权限与角色种子。  
3. API + 解析器 + 前端。  
4. 金样手算：仅内部员工（C 公司段 ∪ 我司姓名格），与系统对齐。  
5. 功能开关可回滚。

## Open Questions

- 权限字符串细分 vs `staffing:write`：实现前定。  
- 恢复已作废事实：本期不做。
