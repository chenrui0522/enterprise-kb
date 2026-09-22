## 1. 数据模型与索引字段

- [ ] 1.1 为 documents / document_versions（及必要时相关表）增加 department_id、project_id、kind 列与迁移，验证 `uv run alembic upgrade head` 成功
- [ ] 1.2 扩展 ChunkRecord / Milvus schema 与 insert 路径写入三标签，验证单元测试断言字段落库
- [ ] 1.3 确定集合升级或重建策略并更新配置/README，验证新 collection 或重建步骤可执行

## 2. 可见性与过滤

- [ ] 2.1 实现 `resolve_corpus_scope(principal)`（或等价）并编译为 Milvus expr，验证矩阵四条规则的单元测试全绿
- [ ] 2.2 将 scope 接入 `build_filter_expr` / `SearchService`，缓存键包含部门与项目集合，验证串用户缓存不会命中
- [ ] 2.3 文档列表查询应用同一可见性谓词，验证不可见文档不出现在列表

## 3. 上传与入库

- [ ] 3.1 上传 API 必填 kind，department 默认用户主部门，project 可选；校验项目成员与 spec 同部门，验证非法请求 403/422 且无任务入队
- [ ] 3.2 pipeline / parent-child 写入将版本标签继承到每个 chunk，验证 pipeline 测试覆盖标签继承
- [ ] 3.3 重导/版本替换使用更新后的标签，验证旧版本切片不再可检索

## 4. 问答链路

- [ ] 4.1 chat 检索路径注入当前 Principal 的 scope，验证不可见 spec 不会进入 hits/citations 的集成测试
- [ ] 4.2 父块展开与图片/表格附件读取前校验文档可见性，验证对不可见文档返回 404/403

## 5. 存量与运维

- [ ] 5.1 编写存量默认值策略（如 kind=general、project 空、department 指向运维指定部门）与 reindex 步骤，验证抽样文档重导后 chunk 带齐标签
- [ ] 5.2 README 说明标签含义、可见性矩阵、与 `add-auth-and-rbac` 的依赖顺序，验证说明与接口一致

## 6. 验证

- [ ] 6.1 用组织样例数据端到端验证：同项目跨部门 fault 可见、spec 不可见、未参与项目全不可见、部门公共库仅同部门
- [ ] 6.2 运行 `uv run pytest -q`，验证全部通过
