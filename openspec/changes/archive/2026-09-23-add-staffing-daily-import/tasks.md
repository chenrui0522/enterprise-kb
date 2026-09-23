## 1. 数据模型与权限

- [x] 1.1 新增 `staffing_import_batches` 与 `staffing_attendance_facts`（含 person_kind、status、void 元数据、batch/project 关联）并写 Alembic 迁移，验证 `alembic upgrade head` 成功且空库可建表
- [x] 1.2 种子权限 `staffing:read` / `staffing:write` 并挂到试点角色，验证无权限用户调用 staffing API 返回 403
- [x] 1.3 原文件存 MinIO（或既有对象存储）并在 batch 记录对象键，验证上传后可按键取回原 xlsx

## 2. 日报解析与项目匹配

- [x] 2.1 实现 OOXML 校验与多级表头定位（日期、C 列现场施工人员、各阶段我司人员姓名格），验证非标准文件被拒且提示另存
- [x] 2.2 解析【公司人员】为人名且忽略【外包人员】整段，验证有名/无名外包均不进入解析人员列表
- [x] 2.3 解析我司人员姓名格为 `internal_contract`，与公司段并集；同人同日正式优先，验证双源去重与 kind 优先级单测
- [x] 2.4 实现文件名/标题抽项目号并在已授权项目中匹配（唯一绑定 / 零或多条待复核），验证三种匹配结果单测
- [x] 2.5 产生告警集合（ambiguous_person_token、same_day_conflict、missing_date、project_*、source_mismatch 等），验证样表或夹具能打出预期告警码

## 3. 导入 / 复核 / 确认 API

- [x] 3.1 `POST /api/v1/staffing/imports` 上传解析并创建 batch，验证返回 batch id、告警与建议 project
- [x] 3.2 `GET .../imports/{id}` 与 `POST .../review` 决议告警（含人工改项目/改名），验证未决告警时 confirm 被拒
- [x] 3.3 `POST .../confirm` 单事务：重叠日旧事实作废 + 写入新 active 事实，验证非重叠旧日仍 active
- [x] 3.4 确认与复核路径写 `write_audit` 与 `staffing.import.*` / `review.*` / `confirm` ops 事件，验证审计可查且运维日志无日报全文

## 4. 汇总与作废

- [x] 4.1 `GET .../projects/{id}/summary` 返回内部员工有谁/在场天数（可按 formal/contract 分组），验证不含外包且文案不用「工时」
- [x] 4.2 `GET .../facts` 明细（日×人×kind×status），验证仅项目成员可读
- [x] 4.3 `POST .../void` 支持 day_person / person / batch 三种 scope（P3），验证软作废后汇总变化且审计 `staffing.void.*` 落库
- [x] 4.4 作废路径打 `staffing.void` ops 事件（scope、count、duration_ms），验证可按 request_id 串起

## 5. 前端人员投入页

- [x] 5.1 导航增加「人员投入」：上传 → 展示告警复核 → 确认，验证无权限不显示或入口 403
- [x] 5.2 汇总与明细表（正式我司 / 我司·外包性质）及按日×人、按人、按批作废操作，验证作废后界面数字更新
- [x] 5.3 非标准 xlsx / 项目歧义 / 待复核空态与错误提示，验证文案可理解

## 6. 验收与文档

- [x] 6.1 以「项目日报1.xlsx」为金样写解析+汇总回归测试（手算内部员工天数对齐），验证 pytest 通过
- [x] 6.2 越权与未确认不可见正式汇总的用例，验证与规格一致
- [x] 6.3 README 简短说明人员投入导入范围（仅内部员工）、复核、回退与日志审计，验证与实现一致
- [x] 6.4 运行 `uv run pytest -q`，验证全部通过
