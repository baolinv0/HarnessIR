# 3. Model × Stage Matrix

## 已核验工程边界

[目标Model-Aware文件](https://github.com/baolinv0/HarnessIR/blob/e1b610ef034d467c8c9172e530d38a930956a3bb/engine/src/hre/model_aware.py#L59)：输入严格A+B，B仅外观；profile集合无NB2。`reference_contracts.py`与v2 profiles把G1映到单次generation流程。正常v2流程不能用来研究原始HarnessIR的Redo收益。

Profile声明不是实测能力；当前Qwen/FireRed local worker接的是两图全帧编辑，FLUX/Fibo依赖外部worker。用户任务明确FLUX.2 Klein，工程已有profile叫`flux3_klein`，二者不得互相冒名。Fibo排除在本次研究外，不因仓库已有而增加研究范围。

## 主模型的最小差异化候选

下表“候选”均需E0–E6验证，尚无已证实的画质收益。

| Stage | 共享层保持什么 | NB2需核验/候选 | Qwen-Image-2.1需核验/候选 | 何时不应差异化 |
|---|---|---|---|---|
| S1 Diagnosis | 相同退化/区域/证据不确定性；与Executor名称分离 | 在固定诊断下测保真约束是否有效限制虚构 | 同一诊断下测“可恢复区域”描述是否过度扩大保护 | 没有跨模型可靠风险校准时，不添加固定“更容易幻觉/能力弱”标签 |
| S2 Evidence | 按同样需求调工具；证据有置信度、坐标、来源、有效状态 | 原文提示与精简语义提示下分别测OCR/face保真收益 | 同内容不同编码（区域语言、结构化文字）是否保留到最终prompt | 准确证据对两模型均有效时共用；别把maps直接塞给Editor模拟控制接口 |
| S3 Composition | 同一目标/保护/不确定性账本；照片可定位区域 | 长详细prompt与等信息短prompt交叉比较；不预设详细更好 | 语义指令/目标状态/操作顺序等信息重编码；官方PE另列因子 | 专属表达只比弱统一prompt强，或收益可由长度/信息解释时，采用更强共享prompt |
| S4 Execution | 单一源LQ；真实参数/版本/输入输出回执；同模型各策略同预算 | 固定模型ID/版本；记录服务端不可控随机性和重试；原方形路线与原生比例比较 | 单图原生pipeline；显式宽高、output_resolution、steps/true_cfg/negative_prompt/cache/precision/seed | 接口适配必要，不能据此声称策略收益；统一step/CFG数值不代表公平 |
| S5 Verification/Refinement | 相同质量目标、保真准则；独立最终评分；同等候选预算 | 对文字重绘/结构漂移出现时检验约束补强是否优于重采样 | 对残余拖影/欠增强时检验局部恢复目标是否优于重采样 | 若统一失败分类与动作同样有效，不加model router；没有GT时不以锐利作为正确性 |

辅助对照只在主模型得到明确因果结果后使用，优先用于检验“表达策略能否迁移”，不开展完整四模型搜索。

## S5六类原因的证据要求

| 原因标签 | 可接受证据 | 禁止的捷径 | 最小干预 |
|---|---|---|---|
| diagnosis_error | 独立LQ标注不同意具体退化/区域，纠正后稳定救回 | 输出不好→诊断错 | 固定tools/prompt预算，仅修一项诊断 |
| evidence_insufficient | 必要证据缺失/错误，补入经核对证据可救回 | OCR没返回→原图无文字 | 固定诊断与表达，真实证据vs去除/打乱证据 |
| prompt_encoding | 意图相同，Executor消费的表达不同，跨seed可重复改善 | 更长或更激进→专属表达有效 | 固定意图与信息长度档位，交叉两个表达策略 |
| execution_mismatch | 输入尺寸/参数偏离已冻结原生配置；单独修复有效 | 任意调CFG后挑最好 | 一次只改一个参数/几何/颜色因子 |
| executor_limit | 已覆盖有限预注册Direct+Harness策略仍失败，已排除前几类 | 几次失败→模型绝对能力上限 | 报“在已测试策略/预算内未解决”，给成功/失败包络 |
| verifier_error | 独立GT/盲评否定在线accept/排名 | VLM自己的解释=真因 | 固定候选池，换独立评分/顺序；测误拒、误收、rank regret |

root_cause允许`unknown`和多原因；动作应带证据引用、置信度和反事实预测。Verifier的单次自述不能建立因果诊断。模型专属风险只能由开发集校准后提出，测试集不再更新。
