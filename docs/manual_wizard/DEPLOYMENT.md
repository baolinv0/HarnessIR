# 可选远程环境

Controller、SSH/Colab 客户端和 T1–T4 模型环境分别安装。源码仓库不携带已有 venv、账号授权或远程会话绑定。以下安装属于显式联网部署准备；模型正式推理继续使用 offline 合同。

## SSH 客户端

本次留存客户端版本为 Paramiko 4.0.0。可新建独立环境：

```powershell
py -3 -m venv runtime/remote_monitor/venv_transport
& runtime/remote_monitor/venv_transport/Scripts/python.exe -m pip install -r engine/requirements-ssh.txt
```

在 `runtime/remote_monitor/known_hosts` 配置经过核对的服务器 host key；该文件不随仓库发布。`engine/scripts/remote_host.py` 默认拒绝未知/已改变的 host key。首次使用的 `--accept-new-host-key` 是显式信任选择，不应当作已经验证服务器身份。当前脚本要求 known_hosts 文件先存在。

每次传入自己的 `--host`、`--port`、`--username` 与仓库外的 `--password-file`，不再提供原工作区的租用服务器默认地址。`--action run` 还要求本地经过审查的 `--command-file`。不要把凭据放进命令文本、argv、Git 或报告。

`--action inspect` 使用历史服务器准备逻辑，涉及关机计划检查/设置。应先审阅 `engine/scripts/inspect_remote.py`，明确获得计算时间与关机操作授权；不要把它当作无副作用的 GPU 查询。容器可能不支持系统关机，计算截止也不等于停止计费。

## Colab CLI

现有 Windows 客户端基于官方源码 revision `d4f855d885cf39f47af5bcae9cd7f7963c18ef09`，安装版本标签 `0.7.4+git.d4f855d`。当时 PyPI 0.7.4 在 Windows 启动缺少 termios，因此记录实际 source pin，不自动升级或声称最新版本。

```powershell
py -3 -m venv runtime/colab_client/venv
& runtime/colab_client/venv/Scripts/python.exe -m pip install "google-colab-cli @ git+https://github.com/googlecolab/google-colab-cli.git@d4f855d885cf39f47af5bcae9cd7f7963c18ef09"
& runtime/colab_client/venv/Scripts/python.exe engine/scripts/colab_client.py --help
& runtime/colab_client/venv/Scripts/python.exe engine/scripts/colab_client.py sessions
```

最后一条命令可能启动官方 Google OAuth 流程，需要账号本人完成。授权码只填回本地终端。launcher 把 token、日志、代理状态放入 `runtime/colab_client/private/`；整个 runtime 已被 Git 排除。

查看 sessions 不等于 GPU 或远程执行验收。浏览器中已有 runtime 也不一定有可用 CLI 会话绑定。先分别验证远程执行、文件上传下载、图像保存与 CUDA，再部署模型。`engine/scripts/colab_attach_existing.py` 依赖实际已有授权/assignment，不自动保证任何账号可连接。

Notebook/runner 需要自己的输入 ZIP、官方授权权重和冻结 source/environment lock。输入准备脚本引用原工作区的 manifest 与 selection；新环境必须提供真实输入与账本。原版 SAM3 与 SAM3.1 独立替代不能混写合同，也不能直接用已经运行过的 notebook 输出充当本次推理验收。

## 运行资产

`runtime/`、`cases/`、`Data/annotations/`、`models/` 均在本机或用户的计算环境中单独保存。恢复既有实验需要原始文件、case 快照、严格匹配缓存、冻结 export ledger 与执行回执；源码克隆不会恢复这些资产。文件出现、权重下载完成、模型列表可见和单纯 API 连接成功分别记录，不等同于真实恢复成功。
