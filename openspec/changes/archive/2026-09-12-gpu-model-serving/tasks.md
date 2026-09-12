## 1. GPU 化部署配置

- [x] 1.1 新增 `docker-compose.gpu.yml`，为 `model-service` 申请 GPU，验证 `docker compose -f docker-compose.yml -f docker-compose.gpu.yml config` 可正常渲染
- [x] 1.2 用 override 重建 `model-service`，验证容器内 `torch.cuda.is_available()` 为 True

## 2. 模型启动脚本

- [x] 2.1 重写 `scripts/init-models.ps1`：`sentence_transformers` 引擎、`n_gpu=1`/`gpu_idx=[0]`、幂等跳过已在线模型、轮询就绪、支持 CPU 回退
- [x] 2.2 重写 `scripts/init-models.sh`：与 PowerShell 脚本行为一致
- [x] 2.3 执行启动脚本，验证 `/v1/models` 中 bge-m3 与 bge-reranker-v2-m3 的 `accelerators` 均显示 CUDA

## 3. 性能参数

- [x] 3.1 新增 `KB_EMBED_BATCH_SIZE` 配置（默认 32），入库流水线改用该配置替代硬编码 32，验证单元测试通过
- [x] 3.2 调高本机 `KB_RERANK_MAX_CONCURRENCY` 并更新 `.env` / `.env.example` 注释说明，验证配置加载后的取值正确
- [x] 3.3 调整 embedding 进度日志频率，使大批量下仍可观测，验证代码可导入

## 4. 文档

- [x] 4.1 README 增加 GPU 启动方式、批大小/并发建议与显存说明，验证命令与实际 compose 文件一致

## 5. 验证

- [x] 5.1 记录 GPU 基准：embedding 128 条一批与 rerank 20 条文档的耗时，验证相对 CPU 基线明显下降
- [x] 5.2 运行 `uv run pytest -q`，验证全部通过
- [x] 5.3 用抽样问答验证检索/重排结果与 GPU 化前一致（无召回回归）