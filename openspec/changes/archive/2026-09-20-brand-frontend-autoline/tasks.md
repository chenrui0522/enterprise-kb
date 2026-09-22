## 1. Brand asset

- [x] 1.1 新增可复用 `BrandLogo`（内联 SVG 圆形狼标，支持 `size`），在 Story/页面外单独渲染确认任意尺寸清晰无糊边
- [x] 1.2 从 `ChatPage` 移除对侧栏/欢迎区 `SparkleIcon` 作为品牌标的依赖（可删或仅留非品牌用途），确认不再出现星芒占位作为品牌标

## 2. Surfaces

- [x] 2.1 更新 `LoginPage`：展示 `BrandLogo` +「奥特莱 · 企业知识库」标题（可选小号英文副标题），目视确认登录页品牌标与文案齐全
- [x] 2.2 更新 `ChatPage` 与 `DocumentsPage` 侧栏品牌入口为 `BrandLogo` + 品牌文案，目视确认两侧栏一致且不严重换行
- [x] 2.3 更新问答欢迎空态：圆形品牌容器 + `BrandLogo`，文案可保留助手介绍但去掉 Sparkle 占位，目视确认空态为大圆标
- [x] 2.4 将 `index.html` 的 `<title>` 改为含奥特莱与企业知识库的标题，打开应用确认浏览器标签文案正确

## 3. Palette

- [x] 3.1 调整 `styles.css` 中 `--accent` / `--accent-dark` / `--accent-soft`、登录背景与欢迎品牌容器样式为品牌蓝系浅色工具壳，目视确认主强调色无紫偏且壳层仍为浅色

## 4. Acceptance

- [x] 4.1 手动走查登录 → 问答空态 → 文档侧栏三触点，对照 `frontend-branding` 规格三条需求全部满足
