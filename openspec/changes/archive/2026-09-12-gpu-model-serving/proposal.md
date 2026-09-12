## Why

词嵌入（bge-m3）与重排（bge-reranker-v2-m3）目前跑在 CPU 上：每批 32 条的 embedding 约需 20-30 秒，
全量入库与在线检索延迟都受限于此。本机已有可用的 NVIDIA RTX 5060 Laptop（8GB）与 Docker GPU 直通
（容器内 `torch.cuda.is_available()` 已在 `--gpus all` 下验证为 True），具备切换到 GPU 推理的条件，
同时应把 embedding 批大小与重排并发从 CPU 时代的保守取值调高。

## What Changes

- 新增 `docker-compose.gpu.yml` override：为 `model-service` 申请 GPU，保持基础 `docker-compose.yml`
  在无 GPU 机器上仍可启动（GPU 为显式可选）。
- 重写 `scripts/init-models.ps1` / `init-models.sh`：显式使用 `sentence_transformers` 引擎与 GPU
  （`n_gpu` / `gpu_idx`），启动前检查模型是否已在线（幂等），移除硬编码虚拟环境路径的安装兜底。
- 新增配置 `KB_EMBED_BATCH_SIZE`（默认 32，本机 128）并让入库流水线使用它，替代硬编码的 32。
- 调高本机 `KB_RERANK_MAX_CONCURRENCY`（10 → 32），并保留为可配置项。
- 更新 README：GPU 启动方式、批大小与并发建议、显存说明。
- 非目标（后续变更）：MinerU OCR GPU 化；模型 bf16/fp16 量化；worker 多任务并发；更换推理框架。
- 无 API 行为变化，无 **BREAKING**：不申请 GPU 时仍按原方式 CPU 运行。

## Capabilities

### New Capabilities
- 无。本变更属于部署与性能调优（tooling / config），对外接口与检索行为不变，故在
  `.openspec.yaml` 中声明 `skip_specs: true`，不新增或修改规范。

### Modified Capabilities
- 无。

## Impact

- 部署：新增 `docker-compose.gpu.yml`；`model-service` 以 GPU 方式重建并重新 launch 两个模型。
- 代码：`app/core/config.py` 新增 `embed_batch_size`；`app/ingestion/pipeline.py` 使用该配置并调整进度日志。
- 配置：`.env` / `.env.example` 增加 `KB_EMBED_BATCH_SIZE`，调高 `KB_RERANK_MAX_CONCURRENCY`。
- 脚本：`scripts/init-models.ps1`、`scripts/init-models.sh` 重写为 GPU + 幂等。
- 文档：README 的模型服务与 MinerU 章节更新 GPU 说明。
- 不受影响：Milvus、Postgres、Redis、API、worker 消费逻辑、已入库数据。