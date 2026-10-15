# 本次方案包验证记录

2026-10-12，交付类型：设计与协议包。

**文件级验证 PASS**：

| 检查 | 结果 |
|---|---|
| JSON Schema 结构 | 10 份通过 Draft 2020-12 检查 |
| 合法协议夹具 | 11 份通过对应 Schema |
| 错误协议夹具 | 10 项均被拒绝，含布尔字符串、非法路径、时间格式 |
| Prompt 模板 | 7 份完整渲染，execute 仅含 instruction、verify 不泄露 editor Prompt |
| 官方快照 | 20 个文件 Git blob SHA-1 和 bytes SHA-256 与锁定来源一致 |
| 文档链接 | 9 个入口链接存在 |
| 源码语法 | 交付验证脚本通过编译检查 |

Schema 无法证明模型看过图像或真实文件已传递；需要 Controller 运行时语义校验。完成标记示例仅关联合成 JSON fixture。

校验期间发现 jsonschema 的默认安装缺少 date-time 校验器，已明确加入 rfc3339-validator 依赖和启动检查，防止错误时间字符串被静默放过。

本次未测试：Windows 安装执行、用户 C 盘读写、本地 App 能力、真实图像编辑、Controller 运行、真实照片实验。PowerShell 安装脚本已做静态检查；不可称本机安装成功。压缩包 CRC 与 PACKAGE_MANIFEST 文件哈希在最终交付前另行检查。

复查命令（可使用独立 venv）：

```powershell
python -m pip install -r scripts/requirements-validation.txt
python scripts/validate_package.py
```

验证脚本不运行官方 API 代码，不调用模型，不安装应用。
