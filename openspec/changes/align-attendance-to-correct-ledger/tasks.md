## 1. Baseline & exemptions

- [x] 1.1 Add正确表手工例外豁免清单（JSON 或 md，含人员/列或日期 + 简短理由）并对照 `考勤全面对比-系统vs正确表-d27cdf6f.md` 初填候选 — verify 清单可被脚本加载且至少含 1 条已标明手改项（如证实的张楠杰调休）
- [x] 1.2 Wire compare harness（扩展 `_compare_att_xlsx.py` 或 pytest）支持豁免过滤并输出非豁免失败列表 — verify 对当前 d27 导出跑一次时「非豁免 diff > 0」可复现为失败/报告

## 2. Domain rules

- [x] 2.1 Implement/verify 出差驻地裁剪（回司/早归）与晚出发 ≥18:00 计 1 天 — verify 单元或夹具场景：回司日不计差；18:00 出发日记整天差
- [x] 2.2 Implement/verify 假勤外地类计差且不双计休假列 — verify 外地假勤→出差列+实出勤；驻地事假→仅事假列
- [x] 2.3 Implement/verify 离职姓名标记 + 末卡后截止 — verify 截止日后不计旷工/缺卡/实出勤
- [x] 2.4 Implement 暂定默认驻地（太原）仅在花名册驻地为空时生效；有驻地则优先花名册 — verify 空驻地走太原裁剪；非空驻地不被默认覆盖
- [x] 2.5 Keep 非出勤日打卡阻塞 + `present`/`full_day`/`ignore` 决议路径；禁止自动计入/自动忽略 — verify 未决议不可确认；`ignore` 后该日不加实出勤

## 3. Chat wiring

- [x] 3.1 Ensure 进度卡/orchestrator 对非出勤日打卡告警暴露上述 prefer 并写回领域 — verify 对话或 orchestrator 测试：`ignore`/`present` 各至少一条 round-trip

## 4. Correct-ledger regression (Aug 2026)

- [x] 4.1 Recompute with 三源 + 花名册 + 月历（含 8/8、8/22）+ `非出勤日打卡-人工决议.json`，导出并跑 compare — verify 非豁免红框/日格差相对 baseline 下降或关键人（周泽江类）保持一致
- [x] 4.2 Freeze 验收门闩：非豁免关键列（应出勤/实出勤/国内/国外/假勤分列/迟到/缺卡/旷工）零失败，或仅剩已登记豁免 — verify CI/本地一条命令可重复跑通

## 5. Cleanup

- [x] 5.1 Document 驻地过渡（何时撤强制默认）于 clerk/README 或 change 备注 — verify 文档中有「花名册驻地优先 / 空则太原」说明
- [x] 5.2 Note supersede 空壳 `attendance-travel-base-punch-clip`（关闭/归档另做）— verify tasks 或 design 中有指向，不强制本 PR 删除目录（见 design Decisions §6）
