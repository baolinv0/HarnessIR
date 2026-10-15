# 状态机、轮次与终止

## 状态及转移

12 个示意阶段合并为 8 个可持久状态；发任务、解析、检查为内部事件，不制造用户需要点击的空阶段。

| 当前状态 | 等待什么 | 转移条件 | 下一状态 |
|---|---|---|---|
| INIT | 已登记且可解码的 canonical | 完成输入与配置锁定，事务发出 diagnoser 任务 | WAIT_DIAGNOSIS |
| WAIT_DIAGNOSIS | Diagnosis JSON | task 身份与 Schema 通过；工具计划非空 | WAIT_EVIDENCE |
| WAIT_DIAGNOSIS | Diagnosis JSON | 工具计划为空；发出 composer | WAIT_COMPOSITION |
| WAIT_EVIDENCE | 计划内工具证据 | 所有必需工具 `ok` 且哈希 / 坐标校验通过 | WAIT_COMPOSITION |
| WAIT_COMPOSITION | Composition JSON | 接收到 instruction；登记本轮预算并发 execute | WAIT_EXECUTION |
| WAIT_EXECUTION | 输出图和完成标记 | 身份正确、图片可解码；登记 generation、发 verifier | WAIT_VERIFICATION |
| WAIT_VERIFICATION | Verification JSON | `verdict=correct`、`needs_redo=false`、几何约束通过 | FINISHED / accepted |
| WAIT_VERIFICATION | Verification JSON | `needs_redo=true`、仍有预算且无相同图片重复 | WAIT_REFINEMENT |
| WAIT_VERIFICATION | Verification JSON | `needs_redo=false` 但 verdict incorrect | FINISHED / no_further_gain |
| WAIT_VERIFICATION | Verification JSON | `needs_redo=true` 但预算已耗尽 | FINISHED / budget_exhausted |
| WAIT_VERIFICATION | Verification JSON | 输出与此前轮次像素哈希完全相同 | FINISHED / duplicate_output |
| WAIT_REFINEMENT | Composition JSON | `refine` 输出有效，instruction 有实际变化 | WAIT_EXECUTION（round + 1） |
| WAIT_REFINEMENT | Composition JSON | instruction 不变且格式修复后仍不变 | FINISHED / no_prompt_change |

`operation_status` 与阶段分离：`active|paused|blocked|cancelled`。paused / blocked 保持 workflow_status、round 与 pending_task_id。失败任务响应 `status=error` 进入 blocked，不自动生成新编辑任务。取消创建终止事务：FINISHED / cancelled，success=false。

## 判定顺序与矛盾响应

1. 外层身份、Schema 与资产校验失败：拒收，当前阶段不变；写 quarantine 与事件。
2. `verdict=correct` 同时 `needs_redo=true`：视为响应矛盾，要求同一 verifier 任务解释 / 修正 JSON；不消费编辑预算。
3. `verdict=correct` 但有 fail checklist 或 moderate/severe defect：响应矛盾，同上。mild defect 可为可忽略残留，但必须 reasoning 解释且该 checklist 非 fail。
4. 图片几何不合规时不允许成功。Verifier 可反馈后走 refine；预算耗尽时只能 incomplete。
5. 合法 verification 到达后按上表做 finish 或 refine，不从 score 分数臆造一个隐藏 success 阈值。

无信息可恢复时 verifier 可以给 `incorrect + needs_redo=false`：这表示继续采样可能编造，不代表成功。报告使用 `workflow_completed=true, restoration_success=false`。

## 工具的例外

正常主组：只运行诊断选择的工具；不能根据 `has_text=true` 再由 controller 擅自增添 OCR。计划空时立即 compose。未知工具 ID 拒收诊断，不能静默忽略。

必需工具报错 / 缺失时 blocked。人工可提交 `skip_tool` 干预理由，之后以 `deviated=true` 单独跑探索 case；不可再算作完整工具主组。`no_detection` 必须是成功执行工具后的空检测结果，不能代替未运行。

## 轮次与预算

本地 round 从 1 开始；verifier 的 `best_round` 保留官方零基 attempt index：0 对应 round_001。request.context.attempts 明列 index、round、任务 ID 与图像哈希；禁止凭文件名猜对应关系。

发 execute 前在事务中 reserve 一个 generation 槽。用户实际提交编辑器时记 `execution_submitted`；收到图像 / 服务端明确已生成时记 consumed。超时并不知道模型是否运行时保持 reservation，等待用户确认，不自动释放或重发。明显未提交时可显式取消 reservation；所有变化写日志。重发相同任务响应不会增加 round；外部再次生成计额外生成，不能以“网络错误”抹掉采样成本。

`reserved` 是仍未确认完成 / 取消的槽数；确认本次生成后释放本次 reserved 槽，并按实际生成图片数增加 consumed。派发时检查 consumed + reserved < max_generations；外部意外多生成也如实计数，不能截断账本以伪装守预算。consumed 超过预算后不得再派发，并将 extra_sampling 偏离写入报告。默认一任务一图，正常 consumed 永不超过 3。

## 选定结果

默认遇到第一成功轮次即停止；FINISHED/accepted 交付该轮。若耗尽预算或不可继续，按最后一次 verifier 比较全部历史的 `best_round` 指定候选；排除文件损坏和几何不合规轮次。该索引越界或指向不合规输出则先要求格式修复，仍无法修复时选 earliest valid round 作 **未通过候选**。若无 valid 输出，final_output=null。

Verifier 最后一次 verdict / checklist 描述的是最新图，而 best_round 可能更早。final success 必须取被选中轮次自己的 verification 且 gates 通过；不得把最新轮的成功标在较早图上。所有失败输出保留。baseline 第一完整图不由 harness verifier 帮它选优。

此选图规则是适配版固定规则，与官方 selection.py 的分数与 NR fallback 不完全相同，必须记录差异。

## 持久化与重启

控制器只根据已落盘 request、commit 事务和有效 done 恢复。重启先取得写锁，校验事务连续性，重建 state / events，再扫描未消费 done。部分 `.tmp` / `.part` 永远不推进。任务修复使用相同 task_id 和新 response revision，不重跑模型图像编辑。

不允许被替换或取消的旧 pending task 响应改变新状态；任务身份与发出 revision 一起校验，当前 revision 可能因 telemetry 已更新，具体见文件协议。晚到输出留存、隔离，生成成本照实登记，但不替换当前 pending task。首次正式成功响应被接受后，任何同 task 的不同结果是冲突；不自动取“更好”一份。
