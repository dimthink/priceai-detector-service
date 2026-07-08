# PriceAI Model Detector

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

PriceAI Model Detector 是 PriceAI 使用的独立模型检测服务。PriceAI 主站负责用户入口、站点上下文和报告展示；本仓库负责接收检测任务、调用用户提供的中转接口、运行协议探针，并生成可复用的证据报告。

本项目基于 [canarybyte/veridrop](https://github.com/canarybyte/veridrop) 修改，继续采用 AGPL-3.0-or-later 协议，并保留上游归属与提交历史。PriceAI 的改动主要包括：`priceai.cc` CORS、OpenAI Responses 检测入口、Cloudflare Turnstile 校验、部署默认值，以及与 PriceAI 主站对接的 HTTP 契约。

## 快速入口

- PriceAI 用户入口：https://priceai.cc/api-transit/detector
- 检测服务仓库：https://github.com/dimthink/priceai-detector-service
- PriceAI 主仓库：https://github.com/physics-dimension/PriceAI
- 上游项目：https://github.com/canarybyte/veridrop

## 仓库边界

PriceAI 主仓保留面向用户的体验：

- 模型检测入口与表单；
- API 中转站上下文；
- 报告展示壳；
- 与 PriceAI 其他模块的导航和说明。

本仓库只负责敏感且成本更高的执行层：

- 接收 `base_url`、`api_key`、`model`、`mode` 和协议类型；
- 对用户提供的中转接口运行协议检测；
- 生成报告 JSON、服务侧报告页和报告图片；
- 不持久化原始 API Key；
- 在生产环境启用 Turnstile 与必要的限流防护。

PriceAI 主站通过 `NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL` 调用本服务。

## 支持协议

| 协议 | Endpoint | 检测层级 |
| --- | --- | --- |
| Claude / Anthropic Messages | `POST /api/detect/claude` | thinking signature 可用时具备加密级证据 |
| OpenAI Chat Completions | `POST /api/detect/openai-chat` | 行为与协议级证据 |
| OpenAI Responses | `POST /api/detect/openai-responses` | 行为与协议级证据 |
| Gemini OpenAI-compatible | `POST /api/detect/gemini` | 协议级证据 |

报告与状态接口：

```text
GET /api/status/{job_id}
GET /api/result/{job_id}.json
GET /r/{job_id}
GET /r/{job_id}.jpg
```

完整对接契约见 [PRICEAI_INTEGRATION.md](PRICEAI_INTEGRATION.md)。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,web]"
VERIDROP_JOBS_DIR=.local/jobs \
PRICEAI_DETECTOR_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 \
PRICEAI_TURNSTILE_REQUIRED=false \
.venv/bin/uvicorn web.server:app --host 127.0.0.1 --port 8017
```

然后在本地 PriceAI 主仓配置：

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=http://127.0.0.1:8017
NEXT_PUBLIC_TURNSTILE_SITE_KEY=
```

## CLI

上游 CLI 仍保留，用于检测器开发、自托管测试和回归验证：

```bash
.venv/bin/relay-detector ping --model claude-haiku-4-5
.venv/bin/relay-detector detect --model claude-haiku-4-5 --mode standard -o out/test.json
.venv/bin/relay-detector compare out/test.json
```

`veridrop` 仍作为兼容命令别名保留。

## 生产环境

检测服务：

```bash
PRICEAI_DETECTOR_CORS_ORIGINS=https://priceai.cc,https://www.priceai.cc
PRICEAI_TURNSTILE_REQUIRED=true
PRICEAI_TURNSTILE_SECRET_KEY=<Cloudflare Turnstile secret>
VERIDROP_JOBS_DIR=/opt/priceai-detector/web_data/jobs
```

PriceAI 主站：

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=https://detector.priceai.cc
NEXT_PUBLIC_TURNSTILE_SITE_KEY=<Cloudflare Turnstile site key>
```

## 目录结构

```text
src/relay_detector/
  core/                 协议无关的 runner、scorer、models 和 detector base
  protocols/
    anthropic/          Claude / Anthropic 检测器
    openai/             OpenAI Chat Completions 与 Responses 检测器
    gemini/             Gemini OpenAI-compatible 检测器
web/
  server.py             FastAPI 路由和 PriceAI 对接接口
  jobs.py               异步任务队列与报告持久化
  probe.py              提交前模型列表与可用性探测
  image_report.py       报告图片渲染
tests/                  detector 与 web 行为测试
```

包名仍保留为 `relay_detector`，这样可以降低与上游结构的偏移，也方便以后把通用检测能力反向贡献给上游。

## 隐私与安全

- 原始 API Key 只应存在于当前任务内存中。
- 报告只存脱敏后的 API Key。
- 生产提交应启用 Turnstile。
- 公开报告是证据材料，不等于 PriceAI 对商家的背书。
- 高成本检测项应保持显式、可感知、可选择。

## 贡献者与上游归属

GitHub 右侧的 Contributors 由提交历史自动统计，不是 README 手动维护的名单。本仓库保留了 Veridrop 的上游提交历史，所以 `tuofangzhe / Tonyhuang` 等上游提交作者会出现在 Contributors 中。

这不是当前 PriceAI 仓库维护权归属的声明，而是保留开源来源链路的一部分。为了遵守 AGPL 与开源归属，我们不建议通过重写历史来抹掉上游作者。更明确的归属说明见 [NOTICE.md](NOTICE.md)。

## 后续维护原则

- 继续保持本仓库作为独立检测服务演进。
- 新检测能力优先放在协议模块或稳定 adapter 后面。
- 不把 PriceAI 主站展示逻辑混进协议检测器。
- 修改 HTTP 契约时，先兼容 PriceAI 主站解析器，再移除旧字段。
- 面向网络提供服务时，继续公开对应修改版源码。

## 许可证

AGPL-3.0-or-later。详见 [LICENSE](LICENSE)。

如果本服务通过网络对外运行，AGPL 第 13 条要求向用户提供正在运行的修改版对应源码。
