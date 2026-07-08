# PriceAI Detector Service Integration

本仓库是 PriceAI 使用的独立模型检测服务。它与 PriceAI 主仓分离，目的是让 AGPL 检测运行时、Veridrop 上游归属、敏感检测任务和后续检测实验都留在一个稳定的 HTTP 服务边界内。

## 来源

- PriceAI 检测服务仓库：https://github.com/dimthink/priceai-detector-service
- PriceAI 主仓库：https://github.com/physics-dimension/PriceAI
- 上游项目：https://github.com/canarybyte/veridrop
- 许可证：AGPL-3.0-or-later
- 运行时：Python 3.10+、FastAPI、`relay-detector`

## 产品角色

PriceAI 主站负责公开入口、站点上下文和报告展示。本服务负责成本更高、风险更敏感的检测执行：

- 接收 `base_url`、`api_key`、`model`、`mode` 和协议类型；
- 对 Claude、OpenAI-compatible、OpenAI Responses、Gemini-compatible API 运行协议探针；
- 生成报告 JSON、服务侧报告页和报告图片；
- 不持久化原始 API Key；
- 生产环境配置校验时，未通过 Cloudflare Turnstile 的公开提交会被拒绝。

PriceAI 主站通过以下环境变量调用本服务：

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=https://detector.priceai.cc
```

用户入口保持为：

```text
https://priceai.cc/api-transit/detector
```

## PriceAI 使用的 HTTP 契约

提交检测：

```bash
curl -X POST "$DETECTOR_URL/api/detect/claude" \
  -F base_url="https://relay.example.com" \
  -F api_key="$TEMP_RELAY_KEY" \
  -F model="claude-sonnet-4-6" \
  -F mode="standard" \
  -F include_long_context=false \
  -F turnstile_token="$TURNSTILE_TOKEN"
```

协议入口：

- `POST /api/detect/claude`
- `POST /api/detect/openai-chat`
- `POST /api/detect/openai-responses`
- `POST /api/detect/gemini`

Turnstile token 字段：

- 推荐：`turnstile_token`
- 兼容：`cf-turnstile-response`

如果设置了 `PRICEAI_TURNSTILE_SECRET_KEY`，每次检测提交都必须携带有效 token。本地开发可以不设置 secret。

轮询状态：

```bash
curl "$DETECTOR_URL/api/status/{job_id}"
```

获取报告 JSON：

```bash
curl "$DETECTOR_URL/api/result/{job_id}.json"
```

打开服务侧报告页：

```bash
open "$DETECTOR_URL/r/{job_id}"
```

PriceAI 也可以把 JSON 渲染到主站自己的报告页：

```text
https://priceai.cc/api-transit/detector/reports/{job_id}
```

## 预期响应格式

提交成功：

```json
{
  "job_id": "abc123",
  "status_url": "/api/status/abc123"
}
```

任务完成：

```json
{
  "job_id": "abc123",
  "protocol": "openai_responses",
  "status": "done",
  "base_url": "https://relay.example.com",
  "target_model": "gpt-5.5",
  "mode": "standard",
  "result_url": "/r/abc123",
  "image_url": "/r/abc123.jpg",
  "json_url": "/api/result/abc123.json"
}
```

报告 JSON 是 PriceAI 报告页消费的证据 payload。可以新增字段；删除或重命名既有字段前，必须先更新 PriceAI 主站解析器。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,web]"
VERIDROP_JOBS_DIR=.local/jobs \
PRICEAI_DETECTOR_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 \
PRICEAI_TURNSTILE_REQUIRED=false \
.venv/bin/uvicorn web.server:app --host 127.0.0.1 --port 8017
```

然后配置 PriceAI：

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=http://127.0.0.1:8017
NEXT_PUBLIC_TURNSTILE_SITE_KEY=
```

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

## 维护规则

- 本服务支撑公开网络检测时，仓库保持 AGPL 与公开源码。
- README、NOTICE 和仓库元信息保留上游归属。
- 用户 API Key 不进入日志、磁盘、报告 JSON 或响应 payload。
- 模型真实性报告是证据，不是商家背书。
- 新检测族优先放在协议模块和测试后面。
- PriceAI 主站对接通过本文档里的 HTTP 契约保持稳定。
