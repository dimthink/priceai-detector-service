# Notice

PriceAI Model Detector 是基于 Veridrop 修改的独立检测服务。

- 上游项目：https://github.com/canarybyte/veridrop
- PriceAI 检测服务仓库：https://github.com/dimthink/priceai-detector-service
- PriceAI 主仓库：https://github.com/physics-dimension/PriceAI
- 许可证：AGPL-3.0-or-later

上游 Veridrop 提供了原始的中转检测架构、协议检测模块、CLI、FastAPI Web 服务、报告模型和测试体系。PriceAI 在此基础上保留通用检测能力，并把仓库定位为 PriceAI 主站调用的独立模型检测服务。

PriceAI 相关修改包括：

- `priceai.cc` 与 `www.priceai.cc` 的 CORS 配置；
- 面向公开检测提交的 Cloudflare Turnstile 校验；
- OpenAI Responses 检测 endpoint；
- PriceAI 检测服务的生产部署默认值；
- PriceAI 主站集成文档与 HTTP 契约；
- 面向 PriceAI 的 README、仓库描述、入口链接和归属说明。

`relay_detector` 包名和 `veridrop` CLI 别名继续保留，用于兼容上游代码、测试和自托管工作流。

## 关于 GitHub Contributors

GitHub 仓库右侧的 Contributors 由提交历史自动统计。本仓库保留了 Veridrop 的上游提交历史，因此上游提交作者可能会显示在 Contributors 中。

这不是 README 或 NOTICE 手动添加的名单，也不代表 PriceAI 当前维护权归属发生变化。保留这些提交历史是为了保留开源来源链路、便于审计修改来源，并符合 AGPL 项目的归属预期。

如果未来需要一个完全没有上游提交统计的展示型仓库，只能通过重新初始化历史或 squash 导入代码来实现。但那会削弱来源可追溯性，也不利于后续与上游同步，因此当前仓库选择保留历史。
