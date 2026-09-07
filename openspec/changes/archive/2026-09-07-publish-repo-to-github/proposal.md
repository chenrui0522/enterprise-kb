## Why

项目（企业知识库 MVP）代码完整、测试自洽，但目前既没有 git 仓库也没有远程托管。代码为个人所有并希望公开，需要把它整理成干净、可公开运行的 GitHub 仓库，获得版本历史并方便展示与二次开发。

## What Changes

- 初始化 git 仓库（默认分支 `main`）并创建首个 commit，只纳入源码与项目文件。
- 强化 `.gitignore`：补充 `enterprise_kb.egg-info/` 与 `.codex/`；继续保持 `.env`、`data/`、`.venv/`、`node_modules/`、构建产物等不入库。
- 新增 MIT `LICENSE` 文件（个人公开项目默认采用；若后续改选 Apache-2.0 或取消许可，仅需替换该文件）。
- 微调 README：明确 docker-compose 中的账号口令仅供本地开发，公开部署前必须修改；确认公开克隆后按文档可独立运行测试。
- 在 GitHub 创建公开仓库（名称取 pyproject 中的 `enterprise-kb`）并推送 `main` 分支。

不涉及应用行为变更，无 **BREAKING** 变更。

## Capabilities

### New Capabilities

无（仓库公开化属于开发流程与工程整理，不新增或修改系统能力规格）。

### Modified Capabilities

无。

## Impact

- 仓库与工程文件：`.gitignore`、`README.md`、新增 `LICENSE`、git 元数据；不修改运行时代码。
- 外部系统：在用户 GitHub 账号下新建公开仓库并完成首次推送（需要 GitHub 认证与网络）。
- 风险与缓解：`.env`（含真实 DeepSeek key）与 `data/`（约 300MB 真实业务文档）已配置忽略；首次 commit 前用暂存清单审查确认，杜绝敏感文件入库。
