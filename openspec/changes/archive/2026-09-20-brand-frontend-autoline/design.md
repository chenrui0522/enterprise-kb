## Context

现有前端在 `enterprise-kb/frontend`：React + 单文件 `styles.css`。品牌相关触点集中在：

- `LoginPage.jsx`：纯文字「企业知识库」，背景为浅紫渐变
- `ChatPage.jsx` / `DocumentsPage.jsx`：侧栏 `SparkleIcon` +「企业知识库」
- 问答欢迎空态：渐变圆角方块 + `SparkleIcon`
- CSS tokens：`--accent: #4c6fff`，欢迎区紫蓝渐变

无独立 UI 组件目录；Logo 需新增共享资产/小组件。见 `proposal.md` 动机；行为契约见 `specs/frontend-branding/spec.md`。

## Goals / Non-Goals

**Goals:**
- 单一可复用圆形 Logo（SVG），在登录 / 侧栏 / 欢迎三处一致使用
- 用 CSS 变量统一品牌蓝，去掉默认紫偏
- 保持现有布局与交互，仅换品牌视觉与文案

**Non-Goals:**
- 营销 Hero、地球/粒子、视频、暗色全站主题
- 英文长标（AUTOLINE LOGISTICS TECHNOLOGY）塞进侧栏
- 后端、路由、权限、文案 i18n 框架

## Decisions

### D1: SVG React 组件，不用栅格 PNG
- **选择**：新增例如 `BrandLogo.jsx`（内联 SVG 圆标：蓝渐变底 + 白色狼剪影），按 `size` prop 缩放。
- **理由**：现有参考图分辨率低、压缩糊；SVG 在侧栏小尺寸与欢迎大尺寸都清晰。
- **备选**：放入 `public/logo.svg` 用 `<img>` —— 也可，但内联组件更易按上下文调色/尺寸；若设计后续提供官方矢量文件，可替换 path 而不改调用点。

### D2: 文案固定为「奥特莱 · 企业知识库」
- **选择**：登录 `h1`、侧栏品牌链接统一该字符串；`index.html` `<title>` 同步。
- **理由**：可读、短、侧栏不挤；英文副标题仅可选出现在登录页小号 muted 行（非必须）。
- **备选**：仅改图标不改文案 —— 品牌识别不足，否决。

### D3: 色板轻改 tokens，不重做布局
- **选择**：调整 `:root` 中 `--accent` / `--accent-dark` / `--accent-soft` 为品牌蓝系；登录背景改为淡蓝灰渐变；欢迎区品牌容器改为圆形 + Logo，去掉紫渐变方块。
- **理由**：改动面小、与「工具型品牌」一致。
- **备选**：登录页深色半屏 —— 属方案 B，已明确排除。

### D4: 顶栏 `App` header 不强制放大 Logo
- **选择**：可选在顶栏左侧加小标，但本变更以登录 + 侧栏 + 欢迎为必做；顶栏保持用户信息/导航为主。
- **理由**：已登录后侧栏已承担品牌；避免顶栏与侧栏双重拥挤。

## Risks / Trade-offs

- [狼剪影还原不精确] → 实现时按参考图近似绘制；若后续有官方 SVG，替换组件内部 path 即可。
- [侧栏文案变长换行] → 使用间隔号「·」控制长度；必要时侧栏仅「奥特莱知识库」缩短一档（实现时以不换行优先）。
- [仅视觉变更无自动化测试] → 以手动验收清单覆盖三触点；不引入截图测试（非本变更目标）。

## Migration Plan

- 纯前端静态资源与 CSS/JSX；部署随前端构建发布即可。
- 回滚：还原相关文件与 assets。

## Open Questions

- 无阻塞项。英文副标题是否出现在登录页可在实现时按版面决定，不影响规格。
