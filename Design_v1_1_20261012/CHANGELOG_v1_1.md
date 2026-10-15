# v1.0 → v1.1 修改清单

| 模块 | 改动 | 对原流程影响 |
|---|---|---|
| Evidence manager | 从纯上传扩展为本地计算 / 缓存导入 / 手动上传 | 输入接口统一，正常用户不再手工跑四工具 |
| 工具调度 | 子进程串行、按需、资源监控、进程退出 | WAIT_EVIDENCE 自动推进，避免多模型驻留 |
| 协议 | evidence 1.1 + tool job / cache / binding / 四类payload schema | ChatGPT request/response 1.0 保留 |
| 缓存 | canonical+bundle+参数+backend+类别+adapter key | 不靠文件名缓存，升级保留旧结果 |
| 图像证据 | OCR polygon、face 5点、float depth、重叠Mask | Composer真实读图，Executor仍只有原图+文字 |
| 实验 | cpu_probe与gpu_full明确分开 | 同名模型不等于同实现，更不等于完整论文复现 |
| 迁移 | 离线 export/import cache bundle | 不新增 Controller 外部API权限 |
| 验收 | 资源、坐标、空检测、缓存、模型升级与隔离 | 完成10图pilot后再280图批量 |

权威增量：[本地工具接入规格](docs/10_Local_Tools_Integration_v1_1.md)。部署与接口资料见 preprocessing/configs、schemas 和 examples/local_tools。程序尚待工程师实现。
