# 机器可校验契约

本目录使用 JSON Schema Draft 2020-12，规范版本 1.0.0，覆盖 Claim 提取、Claim、题目种子、已校验 Observation、程序 Policy Decision、受约束回答/简历生成结果和持久化事件。它们不是完整 REST OpenAPI；全部 HTTP DTO 在施工时按 api.md 用 Pydantic 实现，再导出 OpenAPI 和前端类型。

Schema 只能检查字段和部分逻辑，不会证明引文存在、语义支持、资料属于当前用户、技术参考已审核或业务状态转换正确。这些必须由服务器语义校验和测试补齐。

Observation 中 weight/criterion_id 等必须与服务器冻结的题目 Rubric 相同；即便 JSON 合法，也不接受模型改权重。missing 只适用于已经明确询问的要点；not_assessable 的 level 必须 null。

Decision 是程序产物；不能让模型按这个 Schema 自由决定整个面试。reason_code 与 action 的合法组合以及追问上限由纯 Policy 测试验证。

`operation-event.schema.json` 校验数据库/应用事件对象。发送 SSE 时 event_type 映射到 `event:` 行，剩余字段进入 `data:`，id 行等于 seq。这里采用分离后的 SSE wire envelope，与数据中的 event_type 不重复；将 wire 数据还原时必须用 event 行补回 event_type 再校验。

`examples/validation-map.json` 指明每个示例使用哪个 Schema。示例通过结构检查，不等于题目被技术审核或业务流程测试通过。

运行静态检查：先在隔离环境安装 jsonschema、PyYAML，再执行 `python tools/validate_spec.py`。本工具仅操作文档目录，不联网、不安装业务依赖、不调用模型、不触碰用户仓库。
