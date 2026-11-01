# 验收与工程师交接清单

本包验收分两类：**设计包静态校验**由本轮完成；**运行系统验收**须工程师实现并实测。通过前者不能推出后者通过。

## 1. 设计包校验（当前可运行）

```bash
python -m pip install -r docs/reference_enhancement/v1_20261013/scripts/requirements-validation.txt
python docs/reference_enhancement/v1_20261013/scripts/validate_package.py
```

检查 JSON 可解析、Schema 合法与离线解析、合成payload/envelope夹具、错误输入拒绝、Jinja StrictUndefined渲染和相对文档链接。夹具明确是 simulation_only，不包含已运行图像模型的证据。以 `VALIDATION_REPORT.md` 实际输出为准。

## 2. P0 需求覆盖与实现责任

| PRD ID | 实施任务 | 必测输入与预期结果 |
|---|---|---|
| P0-01、02 | M1、M4 | A/B上传顺序变化仍按绑定；原文件未改；canonical哈希与色彩处理可追踪 |
| P0-03 | M3、M4 | B多天空、人物移动、光线变化标不可比较；unknown不会进入执行成功 |
| P0-04、05 | M2 | 错task/hash/config/revision拒收；重复导入幂等；未完成写入不推进 |
| P0-06、07 | M3 | 同名异图/权重变动cache miss；planned only；A/B/C证据不串 |
| P0-08、09 | M4 | Executor恰好A+B+文字；retry仍A；raw output不覆盖、无颜色回拉 |
| P0-10、11 | M4、M5 | 光度改变允许；结构变更失败；critical defect覆盖pass；冻结selector生效 |
| P0-12、15 | M2、M5 | 已提交失败生成扣budget；未知提交暂停；最大3；恢复不重复计费 |
| P0-13、14 | M4 | 四项capability独立日志；手动导入同协议，图片不按最新文件名猜任务 |
| P0-16 | M5 | COMPLETED successfalse可以成立；无usable明确baseline fallback |
| P0-17 | M1 | 本地盘点与备份；旧case仍能原版本读取；Data保留 |
| P0-18、19 | M2、M6 | Prompt/config/evidence/model显示名/实际调用留记录，unknown不杜撰 |
| P0-20 | M5、M6 | 导出candidate来源；不自动写训练集，不称B/C为GT |

## 3. 必须演练的失败矩阵

| 场景 | 期望行为 | 严禁的行为 |
|---|---|---|
| JSON缺字段、boolean为字符串 | 拒收，最多一次格式修复，状态不变 | 猜默认true或把空回复当通过 |
| Done先到、asset缺失/半文件 | 保持pending，等待完整并验证hash | 看到任一文件就推进 |
| 重复同task同hash | 一次接收，后续返回duplicate | 重复发下阶段/扣预算 |
| 同task不同回复hash | 隔离冲突，人工解决 | 后写覆盖已接收判断 |
| 旧case revision/旧state任务迟到 | 隔离stale；不推进当前case | 把旧图关联新reference |
| pause后回复、cancel后回复 | pause登记待恢复；cancel只审计不重开 | 非当前状态自动推进 |
| A/B原文件同名、canonical不同 | 按角色+canonical hash分开绑定 | 按文件名缓存命中 |
| 证据empty/error/unavailable | 区分；缺计划证据不Compose | 用error当无脸/无文字 |
| 缓存有全部工具，计划只要T2 | Compose仅T2与明确计划的基础统计 | 将所有地图自动送入编辑器 |
| B非对齐、动态人物/物体 | 排除该ROI的迁移目标 | 要求输出复制B物体位置 |
| 风格变好但文字/身份损坏 | contentfail/critical defect，拒绝成功 | NR高分覆盖内容破坏 |
| 风格unchanged但结构完全保留 | usable可review，successfalse | SSIM高判增强成功 |
| output尺寸同A但构图替换 | geometry/content失败 | 尺寸相同视为保真保证 |
| strict尺寸不同 | 拒绝正式候选，保留raw | 静默resize掩盖问题 |
| 可冻结纯scale但aspect差>.005 | 拒绝；不crop/warp | 自动配准让坏图“过门禁” |
| 生成提交成功但存图超时 | 扣已提交budget并PAUSED核对 | 自动发相同任务导致超预算 |
| 第三次仍失败 | 停止、successfalse；合法候选review或fallbackA | 无限重试或把最后图强行成功 |
| 候选与A或之前candidate相同bytes | duplicate_output停止；A重复无改善 | 当成功、继续无意义重试 |
| 多候选早期accepted最后损坏 | 选最早accepted，report绑定其hash | 把最新图与旧通过结果配对 |
| 模型metadata不可观测 | UI显示名+unknown/null | 编造API型号、seed、精确版本 |
| 评审包泄露method/prompt | 阻止正式盲评并重新导出 | 解盲后再更改评分 |
| 正式test同scene入train/dev | 阻止入组/分析，记录泄漏 | 图像编号不同就当独立样本 |

## 4. 真实一图验收 R1

1. 使用用户真实的一个 A/B pair，记录 baseline prediction来源与reference iPhone17来源；不使用合成schema夹具图当实测。
2. 保存canon处理报告，两图在各自坐标中显示；明确比较限制与manual ROI。
3. 真正看图诊断→读取计划内缓存/合法工具证据→Compose→两图编辑→raw C落盘→Verify→规则选择。
4. 至少跑 DirectRef 与 AgentSingle 的单次公平对照；3次预算两臂另记，不能合并解释。
5. 保存每阶段request/response/done、图像hash、config/Prompt版本、人工动作、实际生成、暂停恢复记录。
6. 按四项能力表分别给 supported/unsupported/untested；手动交接可视为链路完成，但不是自动派发通过。
7. 最终报告 selected hash/round/success/terminal_reason 与state一致；独立单例评价保留。

R1只说明链路在当前环境可运行；无需一张图就效果明显才能验收协议，也不能凭一张好图宣称方法有效。

## 5. 12对pilot与正式实验

按04冻结split、各臂、rubric、预算与selector。pilot的GO/PROBE/STOP是工程投入判断，正式测试结论由独立盲評及场景配对统计给出。

至少提供：12对全arm记录（含失败）、实际生成分布、fallback/内容破坏/uncertain表、独立盲评原始评分、解盲映射、预计算与在线/人工成本、问题定位和下一次只改变哪一项。

数据未齐/模型未跑时明确 `not_run`；不能填示例成功率。单次比较与3次上限比较各一张表，不把自带流程Verifier当最终裁判。

## 6. 可复制给工程师的任务

> 请依据 `docs/reference_enhancement/v1_20261013/START_HERE.md` 实现 HarnessRefEnhance v1。先读公共合同与PRD，再读状态/文件协议、Prompt、实验方案、实施计划与验收。先盘点当前engine/Data/cases和适用本地规则，保留已有文件；以 `engine/src/hre/` 独立接入，禁止直接套用restoration颜色回拉/门禁/selector。按M1–M6实现，先合成协议链，再真实一对A/B，再12对pilot。Executor先用ChatGPT桌面两图编辑，不调用外部模型API；能力分项实测，不支持自动交接时走相同校验器的手动通道。工具支持offline预生成及缓存自动消费，A/B/C资产严格隔离；B仅外观参考。每轮固定A+B，最多3次生成，最终style与内容双轴判定；结束不等于成功。完成后回报commit、启动命令、测试、capability日志、真实case、实际成本、失败清单及待做项。

审查后补充：aspect_preserving_resize的0.5%为拒绝初筛边界，派生到A精确尺寸还必须raw_w*A_h==raw_h*A_w；不允许小幅拉伸。固定K臂正常完成即fixed_k_complete（由selector决定success），Adaptive未通过耗尽为budget_exhausted。V1同次返回多图只登记供应商顺序首个完整图为candidate，其他图只存raw审计，已知额外采样仍入budget。
