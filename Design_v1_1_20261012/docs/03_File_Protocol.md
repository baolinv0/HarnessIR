# 文件交接协议 v1.0

## 单任务生命周期

1. Controller 在 `tasks/<task_id>/` 写不可变 `request.json`、`prompt.txt`，更新状态事务。
2. 角色适配器读 request 和允许的资产，执行一次任务。
3. 写 `response.json.tmp`；flush、fsync、关闭，用同目录 rename 替换为 `response.json`。
4. 图片先写 `.part`，关闭后改为最终文件，计算 bytes SHA-256 与解码后的 RGB 像素哈希。
5. 最后写 `done.json.tmp`，关闭并 rename 为 `done.json`。done 内包括 response bytes SHA-256 和所有输出资产哈希。
6. Watcher 只消费 done；校验后由唯一 Controller 提交状态事务。

临时文件与目标在同一卷。Windows 报 sharing violation 时短退避重试（100/200/400/800/1600 ms），仍失败 blocked。不能在文件未关闭时写 done。

## 字段

`request.schema.json`：身份、角色、round、attempt_index、expected_state_revision、输入哈希、profile、模板哈希、prompt_file、payload_schema、allowed_assets、context、response 路径、done 标记路径。

`response.schema.json`：原样回传身份、role、round、revision、input_sha256；status 为 ok 或 error。ok 有对应 payload 且 error=null；error 有 error 对象且 payload=null。provenance 记录实际显示的模型 / 版本、会话与传输方式；未暴露后端版本写 null，不能猜成某个 GPT-Image API ID。

`done.schema.json`：task_id、response_file、response_sha256、artifact_hashes、committed_at。`payload_schema` 指向本包下的 schema；request 只允许在锁定配置中列出的 schema 文件。

数据统一 UTF-8；时间使用带时区的 ISO 8601（推荐 UTC Z）。哈希为小写 64 位 SHA-256，由本地文件桥 / controller 计算，模型不得填想象值。JSON 重复键、NaN、Infinity、字符串布尔值一律拒收。仅允许最外层一个完整 markdown JSON fence；不从自由散文中捞取“看起来像 JSON”的片段。

## 资产与访问范围

文件 path 为 case 内相对路径；拒绝绝对路径、盘符、`..`、反斜杠、符号链接 / junction 逃出根目录。resolve 后必须仍在 case 根。资产声明：path、sha256、kind、width、height；JSON / 文本的 width、height 为 null。图片以解码实测尺寸为准，不能信任 filename。

diagnose 只允许 canonical；compose / refine 允许原图、合法证据与失败反馈；execute 只允许 canonical（实际编辑消息仅送图片 + instruction，文件 envelope 不发送给编辑模型）；verify 允许原图与全部历史输出、固定 intent / checklist / 可用 measurements，不允许 composer / refine instruction。

## 幂等和冲突

幂等键是 `(task_id, response_sha256)`，不是 filename。相同键被处理两次，第二次返回 already_processed，不推进、不增加 round。相同 task 不同内容：首个被校验并接受的 response 为正式值；后续置 quarantine/conflict，不能覆盖正式文件。未通过格式校验的响应可修复为新 revision，但原 raw 全部留存。

文件发现顺序不代表生成顺序。每个 execute task 只有一个 canonical candidate；若编辑器返回多个图片，适配器记录 provider 顺序，采用第一完整图片，其余归档为 extras 并登记多输出，不让人挑图。若顺序无法确定，阻塞并记录为协议偏离。

## 状态事务与事件

`state.json` 是唯一当前状态快照；只有 Controller 可写。`transactions/<revision>_<tx_id>.json` 是持久恢复凭据，含 previous_revision、完整 next_state、event、accepted_response_sha256、next_task_id 与下一任务哈希。

提交步骤：持锁 → 校验当前 revision → 下一任务文件临时落盘并校验 → 事务文件原子提交（commit point）→ 更新 state 快照 → 追加 events.jsonl 并 flush。若任一步断电，重启按已提交 transaction 重放到 state，并按 event_id 去重重建 events.jsonl。未提交的任务目录不派发；跳过 / 不连续 revision 则 blocked。

`events.jsonl` 是可再生审计投影，不与 state 争夺写权限。记录 case_created、task_issued、execution_submitted、response_accepted、response_rejected、tool_registered、state_changed、manual_intervention、case_finished。event_id / tx_id 唯一，不使用本地时间戳作为唯一 ID。

## 降级导入

用户粘贴仅 payload 的 JSON 时，UI 从当前不可变 request 补 envelope；用户只需选择实际模型显示名。UI 保存 raw，再做相同 Schema 检查、文件哈希与 done 提交。`writer=manual_import, transport_mode=clipboard_import`。禁止 UI 在 JSON 解析失败时调用另一模型偷偷改写结果。

用户保存编辑图片后，通过“提交当前任务结果”选择该文件；UI 将 bytes 复制到当前 task 目录，登记 metadata 和完成标记。也可保存为 UI 明示的任务路径，由桥做同一登记动作。不能监控整个 Downloads 后自动把最新图片匹配到某个 case。

## 必须校验的语义规则

Schema 之外：哈希对应锁定 canonical；expected revision 等于任务发出时 revision；role 等于当前 pending role；round / attempt index 映射成立；工具清单只含锁定计划；bbox 的 x0<x1、y0<y1；best_round 对应已展示合法输出；stage payload 的 Schema 选取固定；provenance 时间顺序正确；done 所列文件完整且哈希一致。详情见验收矩阵。

`expected_state_revision` 与 request 中锁定的发出 revision 比较，不与 telemetry 更新后的最新 state.revision 直接比较。登记 execution_submitted 等事件可能更新 state revision，但只要该 request 仍是 pending_task_id，响应可接受；验收事务另外对最新 state revision 做 compare-and-swap。被替换 / 取消的旧 pending 任务响应一律隔离。这样既防旧响应，也不会因记账导致有效输出无法回写。

`date-time` 检查必须真实启用（jsonschema 的默认 FormatChecker 可能缺少可选依赖）；启动自检确认已注册，否则报错并安装 rfc3339-validator。还需校验真实时间顺序与时区，不能只做字符串格式检查。

## v1.1 证据与工具任务

ChatGPT request/response保持1.0，证据和ToolJob单独使用1.1。Worker只写job输出和ready，Controller校验并写state。模型多组件SHA、合同哈希、相对asset路径及证据快照参照docs/10；不能把新payload截断为旧通用bbox。
