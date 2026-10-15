# Manual Wizard 源码发布记录 · 2026-10-15

记录时间：2026-10-15T08:18:43.519821+08:00。在已有上游 HarnessIR / Qwen 适配提交之上增量发布；上游原有代码、许可证及实验文档保持原 blob，只为根 README 加入口，并扩展 .gitignore。

## 验证证据

- 隔离源码副本全套工程测试：**327 passed, 4 skipped, 0 failed / 0 errors**，654.16秒。
- 4项 skip 明确标记为 private_assets：需要未公开的真实SAM3.1缓存、冻结输入/结果ZIP和来源锁。不是模拟通过，也不算真实模型推理验收。
- 相同4项防篡改用例在保有真实资产的原工作区另跑：**4 passed**，10.41秒。一次pytest缓存目录权限警告不影响断言结果；不把缓存写入测试替代缓存协议验证。
- 第一轮清洁副本测试为327通过、4项缺私有文件而失败；补充显式前提检查后重新运行完整套件，结果如上。没有上传私有资产以凑测试通过，没有修改生产验证器或放宽合同。
- 两版设计包只读SHA256校验：92和125个包文件通过；官方来源锁20和25个文件的SHA256及Git blob验证通过。
- 原始设计自检脚本在Windows重渲染TXT后以CRLF与冻结LF比较会失败；已恢复发布副本的原始示例，原模板/来源锁/包manifest不改写。该设计自检限制与工程测试分开记录。
- 源码AST解析、Gemini/SSH CLI帮助入口和notebook输出清理完成。扫描精确Git index，未发现已定义格式的API/OAuth/GitHub/Hugging Face令牌、私钥或带密码URL；扫描不读取本机凭据文件。

工程测试运行命令（从仓库根目录）：

```powershell
& engine/.venv/Scripts/python.exe -m pytest engine/tests -q
# 有完整原工作区资产时，单独重验4项，不安装/调用模型：
& engine/.venv/Scripts/python.exe -m pytest engine/tests/test_sam31_evidence.py -q -k received_archive
```

测试使用Python3.12.14与Controller锁定环境。此发布验证没有新增付费API请求、模型推理或GPU计算，也未建立新的远程计算窗口。已有真实恢复结果与本次源码可用性分别报告，不能将工程通过写成20张恢复验收通过。

## 发布整理

- 两版设计规格、完整engine模块/测试/CLI/UI、preprocessing适配和worker、独立GPU/CPU registry、SAM3/SAM3.1 Colab handoff与数据脚本一并保存。
- 新增START_HERE、README_MANUAL和独立环境部署说明；上游README正文保留。
- 发布副本SSH工具移除旧租用服务器默认地址，改为必填host、默认22端口。原工作区连接配置未改。
- 工程测试新增private_assets标记和缺文件前提检查；真实资产齐备时仍执行原防篡改断言。此项同步回原工作区，便于以后源码克隆测试。
- .gitattributes保持冻结设计与源码字节；.gitignore排除本地照片、GT、权重、缓存、case、日志、虚拟环境和授权文件。所有本地Data及实验资产保留。
- Colab notebook清除执行输出与序号；不携带已有OAuth授权或远程session绑定。

精确发布文件与SHA256/Git blob清单见[source_manifest.json](source_manifest.json)，清单排除自身及本记录以避免循环哈希。其余源文件与历史阶段文档按该快照保存，不把仍在别的会话中继续产生的运行结果自动加入Git。

## 当前功能边界

Gemini编辑、独立Verifier、从原图重试已有真实人像闭环记录；SAM3.1独立替代T4有20张真实证据。**20张完整恢复、原版SAM3正式评测仍不在此源码发布的完成结论中。** 数据、模型与私有冻结账本需另行部署。默认ChatGPT桌面仍保留人工JSON和图片导入通道。
