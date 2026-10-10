## ADDED Requirements

### Requirement: 对话内选择 prior 并合并到当前调休任务
系统 SHALL 允许用户在同一会话内、调休台账工具已挂接**当前未确认任务**且该任务已有计算结果时，显式选择同租户可用 prior 任务（已确认或经正式导出台账导入），并将段级合并结果写回当前任务。合并口径 MUST 与独立调休台账页一致。系统 MUST NOT 在用户未显式选择 prior 并请求合并时自动合并。本轮若同时附带四源企微文件，仍按既有来源收录规则处理，MUST NOT 将四源文件误当作 prior 台账合并。

#### Scenario: 对话中选已确认 prior 合并成功
- **WHEN** 用户会话已绑定未确认且有计算结果的调休任务，并在对话中选择一份已确认 prior 请求合并
- **THEN** 系统写回合并后的计算结果，进度卡反映合并后状态，且 MUST NOT 仅用文档检索编造合并数字

#### Scenario: 未选 prior 不合并
- **WHEN** 用户仅发送含「合并」字样的消息但未指定 prior 任务
- **THEN** 系统拒绝执行合并或提示先选择 prior，MUST NOT 改写当前任务计算结果

### Requirement: 对话内上传正式导出台账作为 prior 后合并
系统 SHALL 允许用户在调休台账对话工作流中上传本系统正式导出的太原一人多行调休台账 xlsx，在用户显式确认将其作为 prior（导入并/或合并）后：先按 leave-ledger 能力导入为可选用 prior（若尚未导入），再可对当前会话任务执行合并。非正式导出模板 MUST 拒绝作为 prior。系统 MUST NOT 将此类文件自动归类为出差/加班/请假/打卡四源之一并写入来源槽位。

#### Scenario: 对话上传导出台账并确认合并
- **WHEN** 用户会话已绑定未确认且有计算结果的调休任务，上传正式导出台账 xlsx，并确认用其作为 prior 合并
- **THEN** 系统完成 prior 可用登记（若需要）并将合并结果写回当前任务

#### Scenario: 导出台账不占用四源槽位
- **WHEN** 用户在调休台账对话中上传正式导出台账 xlsx 且意图为 prior 合并
- **THEN** 系统 MUST NOT 将该文件计入 travel/overtime/leave/punch 任一来源槽位
