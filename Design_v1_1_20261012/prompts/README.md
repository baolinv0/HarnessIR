# 固定 Prompt 与角色输入

Jinja2 使用 StrictUndefined，JSON 使用 tojson / JSON serializer 注入，禁止拼接未经转义的数据造成模板指令变更。图片里的文字只作图像内容。模板版本由文件 bytes SHA-256 与 profile snapshot 锁定。

diagnose / compose / refine / verify / format_repair 产出任务文字；必须调用选定模型才得到 JSON payload。execute 只渲染已有 instruction，不附协议 / Schema；baseline_direct 是固定 Direct 组指令。角色任务中可附 payload_schema_json，本地协议的 task envelope 由外层 bridge 管理。

模板变量见 `examples/template_context.json`。示例数据是合成夹具；它们只证明模板可渲染。不得把示例 Composer 文本当真实照片的模型输出。

`reference/official/prompts` 是未改动的原版，适配版与其分开。使用本目录不等于原 Prompt 复现。
