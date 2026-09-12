# Document Ingestion Specification

## Purpose
支持将 PDF、Word(.docx)、PPT(.pptx)、Excel(.xlsx)、Markdown、TXT、HTML、CSV、JSON 等文档异步接入企业知识库：上传后系统先将文件统一转换为 Markdown，再自动完成切片、向量化与索引，使文档可供知识问答检索使用，并通过状态与进度信息让用户掌握处理结果；文档后续更新时可重新入库替换旧版本。

## Requirements

### Requirement: 上传后异步处理
系统 SHALL 在用户上传文档后立即受理并返回文档标识，随后的解析与入库 MUST 在后台异步执行，不阻塞用户继续操作。

#### Scenario: 上传大型手册
- **WHEN** 用户上传一份数百页的产品手册
- **THEN** 系统立即返回受理成功与文档标识，后台开始处理，上传接口无需等待处理完成

### Requirement: 处理状态可查询
系统 SHALL 为每份文档维护处理状态与阶段进度，用户 MUST 能查询到文档处于排队、解析、切片、向量化、索引等哪个阶段，以及最终成功或失败。

#### Scenario: 查询处理进度
- **WHEN** 用户上传文档后查询其状态
- **THEN** 系统返回当前处理阶段与状态；处理完成后状态为成功，失败时返回可读的错误信息

### Requirement: 文字与表格内容入库
系统 SHALL 从文字版 PDF 中提取正文文本，并 SHALL 尽力保留表格内容语义；每个入库切片 MUST 携带来源文档标识与页码等定位元数据。

#### Scenario: 包含表格的制度文档
- **WHEN** 上传的 PDF 含文字与表格
- **THEN** 系统提取正文与表格内容并切片入库，问答时可检索到表格内信息

### Requirement: 更新文档重新入库
当同一文档被更新后重新上传时，系统 SHALL 将新内容重新解析并索引，并 MUST 使新版本生效后旧版本内容不再参与问答检索。

#### Scenario: 手册修订后重新上传
- **WHEN** 用户上传修订版手册替代旧版
- **THEN** 系统以新版本内容建立索引，并移除旧版本对应的可检索内容

### Requirement: 失败不影响其他文档
单份文档处理失败 MUST NOT 影响其他文档的处理与检索；用户 SHOULD 能重试失败文档。

#### Scenario: 坏文件处理失败
- **WHEN** 上传的某份 PDF 无法解析且处理失败
- **THEN** 系统将该文档标记为失败并给出原因，其余文档仍正常完成入库与检索

### Requirement: 不支持的输入明确报错
系统 SHALL 在接收到不支持的文档格式或损坏文件时返回明确错误，不进入后台处理。

#### Scenario: 上传不支持的文件类型
- **WHEN** 用户上传非 PDF 或损坏的文件
- **THEN** 系统立即返回明确的不支持或损坏提示，不创建待处理任务

### Requirement: 任意支持格式先转为 Markdown 再入库
接入流水线 SHALL 先将 PDF、Word(.docx)、Markdown、TXT 等支持格式归一为统一的文档结构表示（标题层级、段落、列表、表格、代码块及其页码位置），再基于该结构按文档类型切片与向量化；PDF 转换结果 MUST 保留原始页码标记，Word/Markdown/TXT 等无分页格式 MUST 维护章节标题层级用于定位。对不支持的格式 MUST 明确提示，不进入后台处理。

#### Scenario: 上传 Word 文档
- **WHEN** 用户上传 .docx 文件
- **THEN** 系统将标题与表格按文档顺序转换为结构化的块并异步完成切片与入库，状态可查询

#### Scenario: 上传 Markdown 文件
- **WHEN** 用户上传 Markdown 文件
- **THEN** 系统直接基于其 Markdown 结构切片入库，并按标题维护章节层级元数据

#### Scenario: PDF 页码定位保留
- **WHEN** 系统将 PDF 转换为内部结构表示
- **THEN** 生成的切片仍携带原始页码，引用可定位到 PDF 原文页面

#### Scenario: Word 标题层级保留
- **WHEN** 用户上传使用中英文标题样式的 .docx 文件
- **THEN** 系统识别标题层级并在切片的章节路径中保留该层级

### Requirement: 多格式先转 Markdown 支持范围扩展
接入流水线 SHALL 将 .pptx/.xlsx/.html/.htm/.csv/.json 等新增格式同样先转换为 Markdown 后再切片入库；新增格式与 PDF/.docx/.md/.txt 共用同一套 Markdown 感知切片与向量化链路。

#### Scenario: 上传 PPT 演示文稿
- **WHEN** 用户上传 .pptx 文件
- **THEN** 系统将幻灯片文字内容转换为 Markdown 后入库，状态可查询，无分页格式以章节定位

#### Scenario: 上传 Excel 表格
- **WHEN** 用户上传 .xlsx 文件
- **THEN** 系统将表格内容转换为 Markdown 表格后入库，问答可检索到单元格信息

#### Scenario: 上传 HTML/CSV/JSON 文件
- **WHEN** 用户上传 .html/.csv/.json 文件
- **THEN** 系统将可读文本与结构化数据转换为 Markdown 后入库，非法或空内容明确报错

### Requirement: 扫描件与图片经 MinerU OCR 入库
当系统检测到文字层缺失的 PDF（疑似扫描件）或用户上传图片文件时，若已配置 MinerU OCR 服务（`KB_MINERU_URL`），解析器 SHALL 将文件提交给 MinerU 异步解析并把返回的 Markdown 接入统一的切片/向量化/入库链路；图片格式（.png/.jpg/.jpeg）与强制 OCR（`ocr=true`）仅在 MinerU 服务可用时受理，未启用时 MUST 返回明确提示。

#### Scenario: 上传扫描 PDF 自动 OCR
- **WHEN** 用户上传一份无可提取文字层的扫描版 PDF，且已启用 MinerU 服务
- **THEN** 系统先用本地文字解析器尝试，发现无内容后自动切换 MinerU OCR，处理完成后该文档状态为成功且可被问答检索

#### Scenario: 上传图片走 OCR
- **WHEN** 用户上传 .png/.jpg 图片
- **THEN** 系统将图片提交 MinerU 解析为 Markdown 后入库；若 MinerU 未启用则上传时明确提示先配置服务

#### Scenario: 复杂彩页手册强制 OCR
- **WHEN** 用户对复杂版式的彩页手册上传时选择强制 OCR（接口参数 `ocr=true`，仅对 PDF 与图片生效）
- **THEN** 系统不经过本地文字解析，直接交由 MinerU 处理并记录该版本的解析模式

#### Scenario: MinerU 服务不可用时的行为
- **WHEN** MinerU 服务未配置或解析失败
- **THEN** 图片上传被拒并给出配置指引；扫描 PDF 任务失败并给出可读错误信息，可通过重试入口在服务恢复后重新处理

### Requirement: 文档结构抽取
接入流水线 SHALL 在切片前抽取文档结构块，并为每个块记录类型（标题 / 段落 / 列表 / 表格 / 代码）、层级、页码或行号信息；PDF 的表格 MUST 保持其在正文中的相对位置，且 MUST NOT 与正文文本重复写入。

#### Scenario: PDF 含表格
- **WHEN** 用户上传同时包含正文与表格的 PDF
- **THEN** 系统产出顺序正确的正文块与表格块，表格内容不重复出现，且表格块携带所在页码

#### Scenario: Word 标题样式识别
- **WHEN** .docx 使用标题样式标记章节
- **THEN** 系统将标题抽取为带层级的标题块，而不是普通段落

#### Scenario: 结构抽取失败降级
- **WHEN** 某文档无法抽取细粒度结构
- **THEN** 系统降级为通用结构（段落级）继续入库，并记录该文档使用了降级结构

### Requirement: 按文档类型选择切片策略
系统 SHALL 支持按文档类型（faq / policy / sop / table / generic）选择切片策略：FAQ 以问答对为切片单元，制度以条款为切片单元，SOP 以步骤为切片单元，表格以表格或行组为切片单元；无法识别文档类型时 MUST 回退到通用切片策略。

#### Scenario: FAQ 文档切片
- **WHEN** 文档类型为 faq 且内容由问答对组成
- **THEN** 每个问答对生成独立切片，且不与相邻问答对合并或拆分

#### Scenario: 制度条款切片
- **WHEN** 文档类型为 policy 且正文按条/款编号
- **THEN** 系统按条款切分，并为切片记录条款编号与所属章节路径

#### Scenario: SOP 步骤切片
- **WHEN** 文档类型为 sop 且正文包含编号步骤
- **THEN** 系统按步骤切分，单个步骤不被截断，切片记录步骤编号

#### Scenario: 未识别文档类型
- **WHEN** 文档类型未提供且无法从内容判断
- **THEN** 系统使用通用切片策略完成入库，不返回失败

### Requirement: 表格切片保留表头
当表格内容超出单个切片容量时，系统 SHALL 按行组拆分表格，并 MUST 在每个切片重复表头行；每个表格切片 MUST 携带表格标识与行号范围。

#### Scenario: 超长表格拆分
- **WHEN** 一张表格的行数超过单切片容量
- **THEN** 系统输出多个带相同表头的表格切片，并分别记录表格标识与行号范围

### Requirement: 切片元数据可定位
每个入库切片 SHALL 携带切片类型、章节路径（无标题时为文档标题）与类型专属定位信息（条款编号 / 步骤编号 / 问答标识 / 表格标识与行号范围之一），并 MUST 记录生成该切片所用切片器版本。

#### Scenario: 查询切片定位信息
- **WHEN** 检索命中某一切片
- **THEN** 返回结果包含切片类型、页码或章节路径以及类型专属定位信息

### Requirement: 上传时可声明文档类型
上传接口 SHALL 接受可选文档类型参数（faq / policy / sop / table / generic）；参数缺省时系统 MUST 按内容启发式判断或回退通用策略；参数非法时 MUST 返回明确错误且不创建入库任务。

#### Scenario: 声明文档类型
- **WHEN** 用户上传时指定 doc_type=policy
- **THEN** 系统使用制度条款切片策略并为该文档版本记录文档类型

#### Scenario: 非法文档类型
- **WHEN** 用户上传时指定未支持的 doc_type
- **THEN** 系统立即返回明确错误，不进入后台处理
