# HarnessIR Manual Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 人工工程师可直接按本计划实施；本次交付只包含方案与协议资料。

**Goal:** 在用户 Windows 目录建立无外部 API 的文件交接控制器，实现 ChatGPT Executor 的完整可审计恢复流程。

**Architecture:** Controller 单写状态，文件任务桥传递 request / response / done。模型角色产出真实 JSON / 图片；独立验证会话反馈，重试始终使用固定 canonical。UI 和 CLI 复用同一服务接口。

**Tech Stack:** Python 3.11+、Streamlit、Pydantic 2、Jinja2、jsonschema、Pillow、filelock；pytest 用于有意义的状态 / 文件协议验证。扫描器使用标准库，watchdog 非必需。

**Spec:** `docs/01_Engineering_Spec.md`，配套 `docs/02_State_Machine.md` 与 `docs/03_File_Protocol.md`。

## Global Constraints

- Executor = `chatgpt_desktop_image`；控制器禁止外部 API、聊天历史抓取、自动登录 / 修认证、安装或调用 cline。
- profile = `chatgpt_adapted_v1`，case 创建后锁定 intent / config / templates。
- 最大生成数默认 3，格式修复默认 2；只在显式记录的真实结果驱动下推进。
- 根目录 `C:\Users\Lenovo\Desktop\HarnessIR_Manual`；保留已有 Data，不覆盖实验原始资产。
- 唯一 Controller 写 state；所有模型 / 工具 / UI 导入不得自行写 state。
- 地图用于 Composer；Executor 只收 canonical 和 instruction；Verifier 看原图、结果、固定标准，不看 editor instruction。

## Review Focus

- Windows 文件尚未关闭 / App 占用：done 不提前，失败可恢复，不读半文件。
- 多进程与重复监控事件：只推进一次，另一个写进程失败。
- 大图、EXIF 旋转、ICC 与分辨率变化：统一输入，不静默裁切输出。
- 手动保存到错误任务 / 老轮次：隔离并说明，不覆盖新结果。
- needs_redo=false 但 verdict incorrect：终止为 incomplete，不误报算法通过。

## 工程文件与公共类型

工程师在根目录下创建 `engine/`。其源代码目录结构：

| 文件 | 职责 |
|---|---|
| `src/hir_manual/models.py` | State、Request、Response、Transition、EvidenceManifest、Artifact、NextAction 的 Pydantic 类型 |
| `src/hir_manual/storage.py` | 根目录 / case 路径约束、锁、原子写与事务恢复 |
| `src/hir_manual/protocol.py` | 严格 JSON 解析、Schema 与语义校验、done 接收 |
| `src/hir_manual/cases.py` | 输入登记、canonical、配置快照与 case 列表 |
| `src/hir_manual/prompts.py` | StrictUndefined 渲染和模板哈希 |
| `src/hir_manual/tasks.py` | 唯一任务创建、资产允许列表与当前任务查询 |
| `src/hir_manual/evidence.py` | 工具证据导入与缺失清单 |
| `src/hir_manual/workflow.py` | 无 I/O 的转移决策与终止判定 |
| `src/hir_manual/service.py` | 锁内事务操作，对外统一服务接口 |
| `src/hir_manual/transport.py` | 文件扫描 / 手工导入，完成标记生成 |
| `src/hir_manual/reports.py` | 审计报告与 case ZIP |
| `src/hir_manual/ui.py`、`__main__.py` | Streamlit 与 CLI |

`CasePaths(case_id: str, root: Path)` 仅使用受控相对路径；`State` 字段与本包 state schema 一致；`Request/Response` 与 request/response schema 一致；`Transition(next_status: str, role: str | None, terminal_reason: str | None, increment_round: bool)`；`NextAction` 与 state.next_action 一致。`Artifact` 对应 asset schema，`EvidenceManifest` 对应 evidence schema。`ImportResult(accepted: bool, code: str, message: str)` 是导入结果；`GateResult(valid_geometry: bool, observations: dict)` 与 Schema 之外的几何判定对应；`Selection(round: int | None, success: bool, reason: str)` 用于 final。

## Task 1: 存储、Schema 与 case 输入

**Files:** 创建 models.py、storage.py、protocol.py、cases.py、pyproject.toml；测试 tests/test_storage.py、test_protocol.py、test_cases.py。

**Interfaces:** `strict_loads(raw: str) -> dict`；`validate_payload(role: str, payload: dict) -> None`；`resolve_case_path(case_dir: Path, relative: str) -> Path`；`atomic_write(path: Path, data: bytes) -> None`；`create_case(root: Path, source: Path, intent: str, config: dict) -> State`。

- [ ] 写失败测试：拒绝重复 key / NaN / bool 字符串；拒绝 path traversal 与 junction 逃逸；旋转照片只生成同一 canonical；已有原图 bytes 不改；两个写进程不能同时拿锁；写半文件不暴露正式文件。
- [ ] `pytest tests/test_storage.py tests/test_protocol.py tests/test_cases.py -q`：先 FAIL，实现后 PASS。
- [ ] 注册所有本地 Schema；FormatChecker 开启；MAX 50 MiB / 40 MP；照片超限明确报错；原图 + canonical + 处理记录与 config 快照同事务登记。
- [ ] 创建提交 `feat: add case storage and strict protocol validation`。

## Task 2: 纯状态机与重试规则

**Files:** workflow.py；tests/test_workflow.py。

**Interfaces:** `decide(state: State, role: str, payload: dict, gates: GateResult | None = None) -> Transition`；`select_final(rounds: list[dict]) -> Selection`。

- [ ] 写失败测试：no-tools → WAIT_COMPOSITION；缺 face → WAIT_EVIDENCE；正确 → accepted；incorrect/no redo → no_further_gain；第 3 次失败 → budget_exhausted；correct/redo 或 checklist fail → contradiction；best_round=0 对应 round 1；最后 verdict 不误标到较早 selected 图；几何失败不能成功。
- [ ] `pytest tests/test_workflow.py -q`：先 FAIL，实现纯逻辑后 PASS。
- [ ] 对比状态表覆盖所有路径，提交 `feat: implement restoration workflow decisions`。

## Task 3: 任务、Prompt 与事务接收

**Files:** prompts.py、tasks.py、service.py；tests/test_tasks.py、test_recovery.py。

**Interfaces:** `render_prompt(role: str, context: dict, design_dir: Path) -> str`；`issue_task(case: CasePaths, state: State, role: str, context: dict) -> Request`；`accept_response(case: CasePaths, request: Request, response: Response, response_sha256: str) -> State`；`recover_case(case: CasePaths) -> State`。

- [ ] 写失败测试：模板缺变量禁止派发；execute 资产只有原图；verify 不包含 instruction；相同 response 两次只迁移一次；同 task 不同 response 冲突；transaction commit / state / events 每个边界崩溃后 revision 连续；旧任务不改变当前任务。
- [ ] `pytest tests/test_tasks.py tests/test_recovery.py -q`：先 FAIL，实现后 PASS。
- [ ] 创建不可变 request、rendered prompt 哈希；使用单写锁和事务提交点；events 按 event_id 重建，不让模型写日志。
- [ ] 提交 `feat: add task broker and crash recovery`。

## Task 4: 工具与编辑图片导入

**Files:** evidence.py、transport.py；tests/test_evidence.py、test_transport.py。

**Interfaces:** `register_evidence(case: CasePaths, manifest_file: Path) -> EvidenceManifest`；`missing_evidence(state: State) -> list[str]`；`import_payload(case: CasePaths, task_id: str, raw: str, provenance: dict) -> ImportResult`；`import_image(case: CasePaths, task_id: str, source: Path, provenance: dict) -> ImportResult`；`scan_ready(root: Path) -> list[Path]`。

- [ ] 写失败测试：另一图 SHA 拒收；bbox 反序拒收；空检测 accepted / error blocked；depth pickle 禁止；非法尺寸 / 标签图拒收；文件 bytes 仍写入时不消费；坏 done hash 拒收；图片格式完整但比例错进入算法失败记录；手动与文件 transport 结果相同。
- [ ] `pytest tests/test_evidence.py tests/test_transport.py -q`：先 FAIL，实现后 PASS。
- [ ] 扫描 interval=1s；先复制关闭文件再写 done；Windows sharing violation 使用规格中的短退避；时间、输出次序与实际生成数如实记录。
- [ ] 提交 `feat: add evidence and manual/file transports`。

## Task 5: 可用向导、CLI 与报告

**Files:** ui.py、__main__.py、reports.py；tests/test_service_smoke.py、test_reports.py。

**Interfaces:** `get_next_action(case: CasePaths) -> NextAction`；`export_case(case: CasePaths, destination: Path) -> Path`；`main(argv: list[str] | None = None) -> int`。

- [ ] 写失败测试：重启显示同一 pending task；在不完整工具阶段只展示缺失项；report 所选图与 verification 对应；失败输出、人工介入、全部任务都在 ZIP；敏感度不高的 UI 外观不做镜像测试。
- [ ] `pytest tests/test_service_smoke.py tests/test_reports.py -q`：先 FAIL，完成后 PASS。
- [ ] 实现按钮与下一动作；CLI 必须提供 `new --input --intent`、`inspect --case`、`watch`、`import-json --case --task --file`、`import-image --case --task --file`、`export --case --out`。命令解析与 UI 使用同一 service。
- [ ] 工程师安装后用 `python -m streamlit run src/hir_manual/ui.py` 运行向导；`python -m hir_manual watch --root <root>` 运行扫描器。上述是待实现接口，不是本包已能运行的程序。
- [ ] 提交 `feat: add wizard and auditable report export`。

## Task 6: 用户本机能力测试与真实 R0

**Files:** 用户 runtime/capabilities.json、一次真实 case 报告、工程验收记录。

- [ ] 按 docs/04 在 Windows 实测四项能力；先验证文件写入 nonce 再接入模型；未通过用降级 transport。
- [ ] 按 docs/07 真实照片 Direct-1 与 Harness-1 跑完；中断恢复一次；需要时执行受预算约束的 retry。
- [ ] 工程师独立核对报告；分别给出工程通过、恢复质量判定与是否支持算法增益。R0 一张不能支持总体增益。

## 工期与优先顺序

参考估计：Task 1–3 约 2–3 人日；Task 4–5 约 2–3 人日；Task 6 约 1 人日，受本机权限 / App 能力影响。先文件回写链，再整套 UI。禁止一开始为未知自动派发能力投入多天私有接口逆向；探测未通过直接用可靠导入通道。

## 自审与交付

执行者逐项勾选规格与测试覆盖，交付源代码、依赖锁、启动命令、能力探测结果、P0 验收记录和真实 R0 case ZIP。提交前执行以上必要测试一次，新的失败 / 修改才重复相关检查。当前文件是完整实施计划，工程师尚需实现这些模块。
