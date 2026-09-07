## Context

现状与约束（动机见 proposal.md - Why）：

- 项目尚未 `git init`，无历史包袱，首个 commit 是唯一一次敏感内容暴露窗口。
- `.env` 含真实 DeepSeek API key；`data/` 约 300MB，含真实业务文档。两者已被 `.gitignore` 排除，但 `enterprise_kb.egg-info/` 与 `.codex/` 尚未排除。
- 源码、测试与 openspec 文档中无硬编码密钥或公司内部引用；测试全部使用 `tmp_path` 自建夹具，不依赖 `data/`，公开克隆后可独立运行。
- GitHub CLI（`gh`）与 git 身份配置是否存在未知，需在实施时探测。

## Goals / Non-Goals

**Goals:**

- 生成一个可公开的干净首 commit：不含密钥、不含真实业务数据，`.gitignore` 覆盖全部构建产物与本地工具目录。
- 补充 MIT LICENSE，并让 README 在公开语境下依然准确、可独立上手。
- 在 GitHub 创建公开仓库（`enterprise-kb`）并推送 `main`。

**Non-Goals:**

- 不改动运行时代码、API 或系统行为（proposal 已声明 `skip_specs`）。
- 不引入 CI、issue/PR 模板、代码规范类元数据。
- 不重写或翻译 README 全文，不做仓库历史迁移（当前无历史）。
- 不把真实业务文档替换为公开演示语料（后续可作为独立 change）。

## Decisions

1. **仓库名 `enterprise-kb`，而不是本地目录名 `test`。** 与 `pyproject.toml` 的项目名一致，公开名称才有意义。备选：沿用 `test`，会误导访客，故不采用。
2. **默认分支 `main` + 单个首 commit。** 仓库无历史，无需保留旧提交；`master` 已非 GitHub 新仓库默认，不采用。
3. **`.gitignore` 追加 `enterprise_kb.egg-info/` 与 `.codex/`。** 前者是 setuptools 构建残留，后者是机器本地的 Codex 技能文件，均与公开项目无关；`openspec/` 保留入库以展示 spec-driven 演进。备选：额外用 `*.egg-info/` 泛化匹配，属细节，可由实施任务选择是否一并加入。
4. **许可证采用 MIT（用户已确认公开个人项目；proposal 中注明可替换）。** 备选 Apache-2.0 / 不放 LICENSE：若后续想换，仅替换单个文件，不影响任务结构。
5. **首 commit 前设安全检查闸门：`git add -A -n`（dry run）审查暂存清单。** 必须确认 `.env`、`data/`、`.venv/` 等未出现在清单中再正式提交。理由：`.gitignore` 已拦截，但这是公开发布前唯一的真实暴露窗口，值得显式验证而非依赖配置。
6. **推送路径优先 `gh repo create --public --source=. --push`；`gh` 不可用时回退 `git remote add origin` + 手动 push。** 若 git 身份未配置，以 `gh api user` 取 GitHub 账号的 name/login 配置 `user.name` 与 `user.email`（`<id>@users.noreply.github.com`），避免使用本机无关身份。
7. **README 只做小改**：在“快速开始”前加一条安全提示，说明 docker-compose 内嵌账号口令仅供本地开发、公开部署前必须修改，且 `.env` 需自备真实 key。不做全文重写。

## Risks / Trade-offs

- [敏感文件（`.env` / `data/`）被误纳入首 commit] → `git add -A -n` 预检暂存清单；由于无既有历史，首 commit 是唯一暴露窗口，确认后再提交。
- [docker-compose 开发口令（`kb/kb`、`minioadmin`）被扫描器/访客标记] → README 明示仅限本地开发；模板口令为公开仓库常见做法，接受该折中。
- [`gh` 未安装或未登录，导致推送受阻] → 回退 HTTPS remote + push，必要时请用户确认 GitHub 账号并完成浏览器/令牌认证。
- [公开克隆缺少 `data/` 样例文档，体验不完整] → 测试自含夹具可独立运行；`scripts/make_sample_pdf.py` 可现场生成样例。制作合成演示语料列为 Non-Goal。
- [LICENSE 后续需更换] → 单文件替换，风险低，可随时单独提交。

## Migration Plan

- 实施阶段按 tasks.md 顺序执行：清理忽略规则 → README/LICENSE → 安全预检 → 首 commit → 创建远端并推送 → 结果核验（`git status`、`git log`、远端可见性）。
- 回滚策略：远端创建后如需撤销，可删除 GitHub 仓库并把本地 `.git` 目录移除（仍保留工作区文件）；实施时不删除任何工作区内容。

## Open Questions

- 若本机 git 身份缺失，默认以 GitHub 账号自动配置；若用户希望首 commit 使用特定 name/email，可在实施时告知（不影响任务拆分）。
