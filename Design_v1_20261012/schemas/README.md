# JSON Schema 使用说明

采用 Draft 2020-12。所有 `$id` 与 `$ref` 是本地注册的逻辑名称，不需要访问 harnessir.example。Schema Validator 必须显式注册本目录中的所有 Schema 并使用 FormatChecker，不能在线下载未知 Schema。

严格类型：不做 true/false 字符串或 int 的隐式转型。结构验证后继续执行 `docs/03_File_Protocol.md` 的语义校验。Schema 无法验证文件哈希、模型是否看过图片、best_round 是否指向当前案例或工具地图是否合法。

diagnosis / composition 保留官方核心字段名；verification 使用固定 C1–C7 的适配版 checklist。response.payload 根据 role 自动绑定相应 Schema；refine 复用 composition Schema。

`examples/` 是合成协议夹具，图片与哈希不是用户真实实验数据，不能直接送入生产 Controller。
