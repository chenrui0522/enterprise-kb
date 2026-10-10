# 夜间进度（等明天确认）

## 已完成（无需确认）

1. **审批断档后外勤续差**（张霄鹏类）
   - `synthesize_domestic_field_travel_from_punches`：行程结束日 D 后，自 D+1 起连续 `field`（不在公司地点）且未回司 → 合成国内出差。
   - **不要求**与原出差地点文本有交集（按你 20:23 口径）。
   - 单元测试 `test_field_punch_after_travel_end_still_counts_domestic` 通过。
   - 冒烟 formal：张霄鹏国内出差 **31**、8/31 **￥/￥**。

2. **对齐修复**：驻地公司打卡不再因假勤回显「出差」被 `align` 强行盖成 ￥（避免回司日打架）。

3. **豁免**：去掉张霄鹏；新增公维振 8/4、刘云飞 8/19（正确表提前销差/混合回司例外）。生产中心应出勤差异已记在 design Deferred + clerk + 豁免原因。

4. **门闩**：`tests/test_correct_ledger_gate.py` + align 套件应绿（以本地冒烟 formal 为准）。

5. 主规格已写入「审批断档后外勤打卡仍计出差」段落（`openspec/specs/attendance-summary-ledger/spec.md`）。

## 本地 Git（已 commit，未 push）

- Commit: `facd846` — `feat: restore attendance summary ledger and align travel rules`
- Branch: `main` **ahead 1** of `origin/main`
- 未执行 `git push`（等你确认）

## 等你明天确认

1. **Git push**：回复 `推送` → 执行 `git push origin main`
2. **归档** `align-attendance-to-correct-ledger`：回复 `同步并归档` / `只归档不 sync` / `先别动`  
   （续差条款已写入主规格；变更目录里其它 delta 仍可能需 sync）

## 建议明天第一句

「推送，并同步归档 align-attendance」
