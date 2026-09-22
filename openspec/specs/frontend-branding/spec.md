# Frontend Branding Specification

## Purpose

定义企业知识库前端在浅色工具壳下的品牌呈现：Logo、产品文案与主色约束，保证用户在登录与主要工作面能识别奥特莱身份，且不改变问答/文档等功能行为。

## Requirements

### Requirement: Brand mark is visible on primary surfaces
前端 MUST 在登录页、侧栏品牌入口、以及问答欢迎空态展示奥特莱圆形品牌标（清晰可辨的矢量或等价清晰资产），且 MUST NOT 以通用装饰图标（如星芒占位）作为这些位置的品牌标。

#### Scenario: Login shows brand mark
- **WHEN** 用户打开登录页
- **THEN** 页面展示奥特莱圆形品牌标，并与产品名称一并可见

#### Scenario: Sidebar brand entry shows mark
- **WHEN** 已登录用户查看问答或文档页侧栏顶部品牌入口
- **THEN** 该入口展示奥特莱圆形品牌标与产品名称

#### Scenario: Welcome empty state shows mark
- **WHEN** 用户进入问答页且当前无活跃对话内容（欢迎空态）
- **THEN** 欢迎区展示奥特莱圆形品牌标（而非通用占位图标）

### Requirement: Product naming includes Autoline identity
登录页主标题与侧栏品牌文案 MUST 体现奥特莱身份与「企业知识库」产品身份（例如「奥特莱 · 企业知识库」或等价清晰组合），且 MUST 对用户可读（不得仅存在于图片且无等价文本）。

#### Scenario: Login title is branded
- **WHEN** 用户查看登录页标题
- **THEN** 标题文案同时体现奥特莱与企业知识库身份

#### Scenario: Sidebar label is branded
- **WHEN** 用户查看侧栏品牌入口文案
- **THEN** 文案同时体现奥特莱与企业知识库身份

### Requirement: Tool-shell palette uses brand blue
前端设计令牌的主强调色 MUST 使用贴近品牌蓝的色值，MUST NOT 以偏紫/靛紫渐变作为默认强调主题；应用壳 MUST 保持浅色工具型背景（非暗色营销全屏主题）。

#### Scenario: Accent reads as brand blue
- **WHEN** 用户查看按钮、链接强调色或欢迎区品牌相关强调样式
- **THEN** 主强调色呈现蓝色系品牌感，而非紫色主导

#### Scenario: Shell remains light tool UI
- **WHEN** 用户使用登录后的应用壳（顶栏、侧栏、主内容区）
- **THEN** 整体为浅色工具界面，不呈现暗色营销 Hero 或全屏视频背景
