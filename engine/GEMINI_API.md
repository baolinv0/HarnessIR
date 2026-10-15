# 可选 Gemini API 通路

用户已明确授权新增 API 通路。默认仍为 ChatGPT 桌面；新建 Gemini case 才允许调用官方 API，旧 case 的执行器和冻结配置不改变。Gemini结果是独立替代实验，不能标成ChatGPT结果或原版SAM3正式评测。当前沿用工程的角色提示模板和状态机，模型来源由每条回执和响应明确记录。

密钥只从本地文件或 `GEMINI_API_KEY` 读取，不写入 case、不放进 URL、不打印 HTTP 响应错误正文、不打包或发送。现有认证实测已读取官方模型列表。图像模型与文字模型必须显式指定，不自动替换；实际返回的modelVersion和usage保存到任务api回执。

在工程根目录 PowerShell 中运行：

```powershell
# 仅检查认证与可用模型，不生成图片
& engine/.venv/Scripts/python.exe engine/scripts/gemini_route.py models --key-file C:/Users/Lenovo/Desktop/key.txt
# 新建独立通路；已有真实SAM3.1标准缓存时选择该证据配置
& engine/.venv/Scripts/python.exe engine/scripts/gemini_route.py new --input C:/path/original.jpg --image-model gemini-3-pro-image --text-model gemini-3.1-pro-preview --evidence-profile gpu_sam31_v5
# 每次只执行当前一个角色，不自动运行全数据集
& engine/.venv/Scripts/python.exe engine/scripts/gemini_route.py run --case CASE_ID --key-file C:/Users/Lenovo/Desktop/key.txt
# 进入WAIT_EVIDENCE时，按诊断计划严格解析匹配缓存
& engine/.venv/Scripts/python.exe -m hir_manual tools run --case CASE_ID
```

UI启动仍为 `.\engine\start.ps1`，新建case时选择Gemini API并指定模型；当前case界面填写密钥文件路径，再执行当前一步。

实测模型列表与metadata可读不代表generateContent可用。gemini-2.5-pro对当前新用户实际返回404 unavailable；旧失败case保留，不原地改模型，新建显式gemini-3.1-pro-preview配置再验收。

Diagnoser只看原图。工具按实际诊断计划查询完整匹配缓存。Composer看原图、所需证据和图例。Executor只收到canonical原图和编辑文字。Verifier为全新无历史API调用，只看原图和生成结果，不接收编辑文字、诊断或证据。每次重试回到原图，最多三次；Direct/Harness使用不同case，首轮和最终分别保存。返回的额外图片全部归档和计数，不挑选后隐去成本。

使用REST `generateContent`，不安装模型SDK，不依赖computer use。每个任务先写提交记录，返回后先原子保存provider_response.json，再校验/import/推进Controller。中断后已有response可恢复导入；已提交但无返回的unknown任务禁止自动重发，必须先核对供应商结果。没有生成图、拒绝、错误、空响应都不算编辑成功。

新case默认600秒传输预算；早期180秒预算的case保持原配置。若文字角色超时，可显式追加 `--retry-text-after-timeout` 做一次新无历史请求，保存原unknown回执及新600秒传输预算。这不自动重试，不能用于execute，也不再次生成图片。若该文字重试仍失败则继续保留pending，不循环提交。

桥接版本 `hir_gemini_rest_xyxy_v2` 对JSON角色补充工程既定XYXY坐标定义、0–1范围和方向示例；原始模板文件不改写。实测早期Verifier框符合Gemini常用YXYX顺序，旧响应原文保留，不能静默转置或用于精确定位指标。后续回执记录桥接版本、实际源文件SHA及完整请求SHA；这仍不保证模型视觉定位正确，需实际复查。

不静默缩放原图或丢掉Composer证据。编码后的请求超过20 MB会明确停止。模型可能返回不同分辨率；实际尺寸和输出哈希照实记录，不以分辨率变化单独断定内容失败。合成测试只验证桥接与隔离，真实编辑和恢复效果须另外验收。

新增显式大图通路：新建case时追加 `--media-transport files_api_v1`，使用官方Files API上传每张允许资产的原始字节。该配置冻结在新case中，旧inline case保持原配置。上传后检查官方ACTIVE状态、MIME、字节数和SHA256；所有资产通过后才提交角色请求。文件在case内按SHA记录，重用前重新检查服务器元数据；不缩放、不省略证据，不将上传会话URL或密钥写入日志。每文件明确限制100 MiB；上传失败与生成失败分别记录，未知生成不会自动重发。

五张完整证据测试运行/断点恢复：`& engine/.venv/Scripts/python.exe engine/scripts/run_gemini_five.py --key-file C:/Users/Lenovo/Desktop/key.txt`。严格校验20个工具合同，串行运行5个新Harness case；最多3次编辑且每次从原图开始。保留失败/unknown，遇到已记录阻塞不会自动重发；报告在 `runtime/gemini_api/five_complete_20261015/`。上传通路参考：[官方Files API](https://ai.google.dev/gemini-api/docs/files)。

官方协议参考：[图像编辑与生成](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)。
