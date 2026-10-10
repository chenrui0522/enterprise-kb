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

## 等你明天确认

1. **归档** `align-attendance-to-correct-ledger`  
   - OpenSpec archive 流程会问是否 sync delta → main（主规格里部分 delta 条款可能尚未完整合并，除今晚已写入的续差条外）。  
   - 请回复：`同步并归档` / `只归档不额外 sync` / `先别动`。

2. **Git push**  
   - 若夜间已本地 commit，是否 `git push origin main`？  
   - 请回复：`推送` / `先看 commit 再推`。

## 建议明天第一句

「确认：同步并归档 align-attendance，并 push」或按需改口令。
