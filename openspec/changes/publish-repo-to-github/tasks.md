## 1. 仓库清理与工程文件

- [x] 1.1 在 `.gitignore` 追加 `enterprise_kb.egg-info/` 与 `.codex/`（可一并加入 `*.egg-info/` 泛化规则）
- [x] 1.2 全仓扫描确认源码/测试/openspec 中无真实密钥与公司内部引用，`openspec/` 按计划保留
- [x] 1.3 在 README「快速开始」前补充安全提示：docker-compose 账号口令仅供本地开发，公开部署前必须修改，`.env` 需自备真实 key
- [x] 1.4 新增 MIT `LICENSE` 文件（Copyright 使用项目作者名称/年份 2026）

## 2. git 初始化与安全预检

- [ ] 2.1 检查 git 可用性与 `user.name`/`user.email`；缺失时按 design 决策用 GitHub 账号身份配置
- [ ] 2.2 执行 `git init -b main` 初始化仓库
- [ ] 2.3 执行 `git add -A -n` 预检，确认 `.env`、`data/`、`.venv/`、`node_modules/`、egg-info 均不在待暂存清单中
- [ ] 2.4 正式 `git add -A` 并复核 `git status --short` 的暂存文件与文件总数符合预期
- [ ] 2.5 创建首个 commit（信息如 `chore: initial commit for public release`）

## 3. 创建 GitHub 仓库并推送

- [ ] 3.1 检查 `gh` CLI 是否安装并已认证（`gh auth status`）；未就绪时引导用户完成认证或选用回退方案
- [ ] 3.2 执行 `gh repo create enterprise-kb --public --source=. --remote=origin --push` 创建并推送
- [ ] 3.3 `gh` 不可用时回退：提示用户提供 GitHub 用户名 → `git remote add origin` → 配置推送凭据 → 推送 `main`

## 4. 发布后核验

- [ ] 4.1 核验 `git status` 干净、`git remote -v` 与 `git log` 正常
- [ ] 4.2 通过 `gh repo view enterprise-kb`（或网页/API）确认仓库为 public 且首 commit 存在
- [ ] 4.3 汇总仓库地址、推送结果与后续可选项（更换许可证、补充合成演示语料等）
