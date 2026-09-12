## Context

动机见 proposal.md。影响方案的既定事实：

- 本机 GPU：RTX 5060 Laptop，8GB 显存，驱动 592.19（CUDA 13.1）；Docker 已注册 nvidia runtime。
- 现有 `xprobe/xinference:latest` 镜像基于 CUDA 13（torch 2.11.0+cu130），但运行中的 `model-service`
  未申请 GPU，因此 `torch.cuda.is_available()` 为 False，`/v1/models` 两个模型 `accelerators` 为空。
- 瞬态容器 `docker run --gpus all` 已实测可识别该 GPU（compute capability 12.0）。
- 现有 `scripts/init-models.*` 使用旧写法（无 `model_engine`、`device=cpu`、硬编码虚拟环境路径），
  在 CPU 期就出现过启动失败，需要一并修正。

## Goals / Non-Goals

**Goals:**
- 词嵌入与重排稳定跑在 GPU 上，并保留 CPU 作为可选回退。
- embedding 批大小与重排并发可通过配置调整，本机取 GPU 友好值。
- 模型启动脚本幂等、可重复执行，重启 model-service 后可一键恢复两个模型。

**Non-Goals:**
- 不引入 MinerU GPU（二期）、不做 bf16/fp16 量化、不改 worker 并发模型、不更换推理框架。
- 不修改检索/问答的业务行为与 Milvus schema。

## Decisions

### D1 用 override 文件申请 GPU，而不是改基础 compose

新增 `docker-compose.gpu.yml`，仅在其中为 `model-service` 增加 GPU 申请；基础 `docker-compose.yml`
保持 CPU 可启动。启动方式：`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`。

替代方案：直接在基础 compose 写 `gpus: all`。放弃原因是会让没有 NVIDIA GPU 的机器直接启动失败，
背离仓库“CPU 起步、GPU 可选升级”的定位。

### D2 通过 `n_gpu` / `gpu_idx` 指定 GPU，而不是 `device`

Xinference 的 launch API 以 `n_gpu`（含 `auto`）与 `gpu_idx` 控制设备，普通 `device` 字段不会进入
实际启动参数（CPU 期脚本传 `device=cpu` 但日志中没有该参数即为证据）。脚本改为 `n_gpu=1`、
`gpu_idx=[0]`，并保留 `-Device cpu` 回退能力。

### D3 启动脚本显式指定引擎并保持幂等

脚本统一传 `model_engine=sentence_transformers`、`model_format=pytorch`、`download_hub=modelscope`，
启动前查询 `/v1/models` 跳过已在线模型，启动后轮询至就绪；删除按硬编码虚拟环境路径 `pip install`
的兜底（新版 Xinference 会自动为引擎创建虚拟环境并安装依赖，CPU 期失败正源于旧路径）。

### D4 embedding 批大小做成配置，默认 CPU 安全值

新增 `KB_EMBED_BATCH_SIZE`（默认 32），入库流水线不再硬编码；本机 `.env` 取 128。批大小过大会拉高
单次请求延迟与显存峰值，因此保持默认 32 让 CPU/低显存环境安全。

### D5 重排并发从 10 调到 32（可配置）

`KB_RERANK_MAX_CONCURRENCY` 只限制客户端并发请求数；Xinference 侧仍按批处理。GPU 后单次重排
延迟下降，提高并发可减少多请求排队，但过高会放大显存峰值，因此取 32 并在验证步骤测量。

### D6 本期不做显存优化

bge-m3 与重排 fp32 合计约 4.5GB，8GB 显存可容纳；不引入 bf16 以免改变向量/分数细节。若二期叠加
MinerU GPU 或出现 OOM，再评估半精度或错峰加载。

## Risks / Trade-offs

- [CPU-only 机器误用 GPU override 导致启动失败] → 文档写明两种启动方式，基础 compose 不变。
- [WSL2/Docker Desktop GPU 直通不稳定] → 已用瞬态容器验证；实施时先确认容器内 CUDA 可见再重启服务。
- [镜像既有引擎虚拟环境是按 CPU 构建的] → 若 GPU 启动仍回退 CPU，删除对应 venv 目录后重新 launch。
- [并发调高导致显存峰值] → 先跑基准，若异常再回落并发或批大小。
- [重启 model-service 会丢已启动模型] → 幂等脚本作为标准恢复步骤，README 记录。

## Migration Plan

1. 新增 override 文件与脚本/配置改动，运行单元测试。
2. `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d model-service` 重建服务。
3. 确认容器内 `torch.cuda.is_available()` 为 True。
4. 运行 `scripts/init-models.ps1`，确认 `/v1/models` 两个模型 `accelerators` 显示 CUDA。
5. 基准测量 embedding（128 条一批）与 rerank（20 条文档）延迟，记录对比 CPU 基线。
6. 可选：重跑入库/评测，确认召回无回归。

回滚：改用基础 `docker-compose.yml` 启动（不申请 GPU），并把 `.env` 的批大小/并发恢复到 CPU 值。