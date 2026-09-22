## ADDED Requirements

### Requirement: 入库携带组织与用途标签
系统 SHALL 在文档上传受理时接受部门、项目（可选）与用途种类 `kind`；`kind` MUST 由调用方指定且为
`spec` / `fault` / `general` 之一；部门缺省可为用户主部门；项目缺省为空表示部门公共库。这些标签 MUST
持久化到文档版本，并在切片、向量化与索引时写入每个可检索切片。非法标签或违反 `corpus-access` 入库校验
的请求 MUST 被拒绝。

#### Scenario: 切片继承文档标签
- **WHEN** 带有部门、项目与 kind 的文档完成入库
- **THEN** 写入检索索引的每个切片携带与文档版本一致的部门、项目与 kind

#### Scenario: 重导保留或更新标签
- **WHEN** 用户对已有文档触发重新入库并更新 kind 或项目
- **THEN** 新版本切片使用更新后的标签，旧版本可检索内容不再参与问答
