# 贡献 PriceAI Model Detector

感谢你愿意参与 PriceAI Model Detector。本仓库是 PriceAI 使用的独立模型检测服务，基于 Veridrop，继续采用 AGPL-3.0-or-later。

## 快速链接

- PriceAI 检测入口：https://priceai.cc/api-transit/detector
- 本仓库：https://github.com/dimthink/priceai-detector-service
- 上游项目：https://github.com/canarybyte/veridrop
- 架构说明：[DESIGN.md](DESIGN.md)
- PriceAI 对接契约：[PRICEAI_INTEGRATION.md](PRICEAI_INTEGRATION.md)

## 本地开发

```bash
git clone git@github.com:dimthink/priceai-detector-service.git
cd priceai-detector-service

python3 -m venv .venv
.venv/bin/pip install -e ".[dev,web]"
.venv/bin/pytest tests/

VERIDROP_JOBS_DIR=.local/jobs \
PRICEAI_DETECTOR_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 \
PRICEAI_TURNSTILE_REQUIRED=false \
.venv/bin/uvicorn web.server:app --reload --host 127.0.0.1 --port 8017
```

## 欢迎的贡献

| 类型 | 例子 | 要求 |
| --- | --- | --- |
| Bug 修复 | 协议字段误判、报告字段缺失、任务状态错误 | 带回归测试 |
| 新协议或新检测器 | 新模型家族、Responses 能力补充、模型智商检测原型 | 放在清晰模块边界内 |
| 安全与隐私 | API Key 脱敏、日志审计、Turnstile 流程 | 不泄露真实用户凭证 |
| PriceAI 对接 | HTTP 契约、CORS、报告 JSON 兼容 | 先兼容主站再移除旧字段 |
| 文档 | README、NOTICE、部署说明、检测原理 | 中文优先，命令和字段名保持原样 |

## 不在范围内的内容

- 绕过中转站限流、封禁或鉴权的工具。
- 持久化、收集、出售用户 API Key 的逻辑。
- 闭源网络服务扩展。AGPL 要求作为网络服务运行的修改版继续提供对应源码。
- 把 PriceAI 主站展示逻辑塞进底层协议检测器。

## 代码风格

- Python 保持现有结构，优先复用 `src/relay_detector/` 里的 protocol 与 core 分层。
- 外部 API 调用必须在测试里 mock，不在单元测试中调用真实上游。
- 新检测项应解释证据含义，避免把弱行为信号包装成确定结论。
- 影响 PriceAI 主站解析的字段变更，必须同步更新 [PRICEAI_INTEGRATION.md](PRICEAI_INTEGRATION.md)。
- Commit message 使用简短祈使句，可用 `fix:`、`feat:`、`docs:`、`chore:` 前缀。

## PR 前检查

```bash
.venv/bin/pytest tests/
git diff --check
```

如果改动涉及公开页面，建议同时本地启动服务，确认首页、检测提交、报告页和静态资源都能正常访问。

## 上游归属

本仓库保留 Veridrop 的提交历史。GitHub Contributors 会自动显示上游提交作者，这是来源追溯的一部分，不是手动维护的作者名单。

通用检测能力如果适合回到上游，优先保持模块边界清晰，方便后续反向贡献。

## 安全问题

如果你发现 API Key 泄露、报告未脱敏、请求被发送到非用户目标上游、检测结果可被恶意绕过等问题，请不要公开 issue，先走 GitHub Security Advisory 或私下联系维护者。详见 [SECURITY.md](SECURITY.md)。

## 许可证

提交贡献即表示你同意贡献内容以 AGPL-3.0-or-later 授权，与本项目保持一致。
