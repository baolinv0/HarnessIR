# 工程与研究验收

## P0：工程师必须交付的结果

| ID | 验收场景 | 通过证据 |
|---|---|---|
| A01 | 新建一个 case 与重启读取 | canonical / original 哈希固定，state 与配置快照完整 |
| A02 | 无工具诊断 | tool_plan=[] 后直接进入 WAIT_COMPOSITION，无空上传步骤 |
| A03 | OCR + face 计划 | 缺任一项不推进；都 ok 后自动发 composer |
| A04 | Composer 真实输出 | 保存 raw、JSON、instruction 哈希；不是模板拼接结果 |
| A05 | 一次编辑 | 图像生成记录、解码宽高、确切 task 绑定，进入 verifier |
| A06 | 失败后重试 | 原图 SHA 不变；refine instruction 更新；round=2 |
| A07 | 成功与不可恢复 | accepted 成功；incorrect + needs_redo=false 为 incomplete |
| A08 | 达到 3 次上限 | 无第 4 个 execute task；budget_exhausted；保留全部图 |
| A09 | 重启与崩溃恢复 | commit/state/events 任一边界断电后只推进一次 |
| A10 | 自动 / 手工导入一致 | 两种 transport 进入同一验证器和同一 state transition |
| A11 | 报告与导出 | final 对应 chosen round；所有 Prompt、工具、失败、人工事件入包 |
| A12 | 本机能力探测 | 每项有本地证据，未测记录 untested；不虚报自动派发 |

## 失败矩阵

错误 JSON / 重复 key / bool 字符串 / NaN → 拒收并保留 raw；缺字段 → 同任务格式修复；role/task_id/input SHA / revision 不匹配 → quarantine；part 文件 → 忽略；done 哈希错误 → 拒收；同响应重复事件 → 不重复推进；同 task 不同响应 → 冲突；两个 controller → 第二个不能写；工具来自另一原图 → 拒收；bbox 反序 → 拒收；工具进程 error → blocked；空检测 ok → 有效证据；相同输出图片 → duplicate_output；几何错误 → 算法失败，不能靠裁切通过；best_round 越界 → 修复 / incomplete；缺原图文件 → blocked；云端路径与 C 盘混用 → 明确能力失败。

默认不以 mean brightness 变大判恢复成功，也不因与 LQ 的 SSIM 变小判失败。额外输出不可由人选择更漂亮的一张。模板上下文残留 Jinja 占位符属于任务生成错误，不能派发。

## R0：一张真实照片端到端

1. 用户选一张真实拍摄退化图，冻结固定 intent 与输入；不得选择本包合成夹具替代。
2. 记录本机四项能力探测；选择实际可用 transport。
3. Direct-1 生成一次并保留第一图；Harness-1 完成 diagnosis、需要的证据、compose、execute、verify。
4. 若需 retry，进入 Harness-loop 标签；验证原图输入未变、轮次预算与停止规则正常。
5. 中间至少退出 / 重启一次 Controller，确认 pending 任务恢复。
6. 导出一份 case ZIP 与报告，工程师逐项查 task ID、hash、实际模型显示名、工具版本、timestamps、manual events、selected round、terminal reason。

R0 的通过门槛是 **流程真实跑通、交接无歧义、失败被正确记录**，不要求图像一定变好。生成质量未通过也能证明工程闭环正常；最终报告不得把两者写为同一个 GREEN。

## P1

多 case 列表、分角色队列、图像左右比较、当前任务一键复制、导出 ZIP、批量 JSONL manifest、固定离线 runner、人工点击统计。P1 不作为 R0 前置要求。

## 本次交付验收范围

本包只校验文档 / Schema / 模板 / 协议夹具 / 官方快照哈希 / 压缩包完整性。未运行 Windows 安装、未运行 ChatGPT 真实图像编辑、未部署 Controller。工程师需要完成上述 A01–A12 与 R0 后，才可宣称第一阶段系统已实现。

## v1.1 附加验收

参照docs/10第12节：worker串行与退出、empty/error区分、cache失效、CPU/GPU模型升级、polygon/kps映射、Mask重叠与unknown、Composer真实地图输入、正式case快照不可更换。新增Schema/夹具检查不能替代模型部署或10图pilot。
