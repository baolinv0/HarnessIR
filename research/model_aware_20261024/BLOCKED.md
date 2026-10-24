# Blockers

| ID | 缺失证据/环境 | 已检查 | 阻塞工作 | 解锁条件 |
|---|---|---|---|---|
| B1 | 可运行的 NB2 与 Qwen-Image-2.1 endpoint/权重、固定版本 | 本会话 HARNESS/HRE API设置未配置；torch/diffusers及权重未部署；NB2 preview历史路由与3.7自动转3.8造成精确复现风险 | Direct、E0–E6真实推理 | 接入已部署执行器；返回真实identity/参数/usage；不得从模型名猜版本 |
| B2 | 用户本地Qwen改版及逐图trace | 目标分支原始harness与官方一致；旧adapter zip仅离线compiler | 解释用户本地Qwen输出和27B的因果贡献 | 本地实际commit、配置、prompt、原始/交付输出、seed/重复、日志、VLM确切版本 |
| B3 | 冻结数据manifest、scene分组、足量GT及未开发测试集 | 获得作者数据zip目录和单例；未创建/声称冻结测试集 | 泛化、分层、统计效能 | 完成数据许可/去重/配准检查；登记dev/test SHA及独立保管者 |
| B4 | 独立盲评结果 | 本轮可做独立同模型家族审稿；无独立人类图像评分 | 真值与主观画质结论 | 与方案生成分离的评价者执行预注册流程；提交未解盲记录 |
| B5 | 同预算真实成本与API重试计数 | 官方logical counters不含底层retry；无端点usage | 成本/稳定性结论 | 逐次transport attempt ledger，含超时未知计费，不自动重发 |

不要求把凭据放入聊天或版本库；只需在运行环境配置。当前未获可验证的外部GPU环境入口，不能访问用户本地/云端服务器。没有请求、购买或启动付费算力。
