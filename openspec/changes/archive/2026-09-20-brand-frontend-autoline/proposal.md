## Why

企业知识库前端目前使用通用紫色强调色与 Sparkle 占位图标，缺少奥特莱品牌识别；登录页、侧栏与欢迎空态无法体现公司身份。需要在不改成营销落地页的前提下，把 Logo 与品牌色落到现有工具型 UI。

## What Changes

- 引入可复用的奥特莱圆形 Logo（SVG 狼标），替换侧栏/欢迎区的 Sparkle 占位。
- 登录页、侧栏品牌位、问答欢迎空态展示品牌标与「奥特莱 · 企业知识库」类产品文案。
- 调整前端 CSS 设计令牌：主色贴近品牌蓝，弱化紫偏；保持浅色工具壳。
- 非目标：暗色营销 Hero、地球/粒子动效、背景视频、后端/API/权限改动、整站暗黑主题。

## Capabilities

### New Capabilities
- `frontend-branding`: 产品 UI 的品牌呈现——Logo 资产、品牌文案落点、浅色工具壳下的色板约束。

### Modified Capabilities
- （无）现有 `knowledge-qa` / `multi-turn-chat` 等能力的功能需求不变，仅视觉与品牌标识变化。

## Impact

- 前端：`enterprise-kb/frontend`（`LoginPage`、`ChatPage`/`DocumentsPage` 侧栏、欢迎区、`styles.css`、可选共享 Logo 组件/SVG）。
- 无 API、数据库、权限或依赖变更。
- 验收以目视/手动为主；不新增后端测试义务。
