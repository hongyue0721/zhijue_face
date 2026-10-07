# Python 后端实习/初级岗位包｜待哥哥本人两级审核

## 1. 状态与审核对象

**审核状态：未审核。不得进入已批准题库或新场次技术评分。**

- 包目录：`knowledge_packs/python_backend_junior/`。
- `format_version=1.0`，`pack_id=python-backend-junior`，包版本 `1.0.1`（1.0.0 的示例 JD 未用显式分区标题，按本包规则识别不到任何要求，已作废；规则与六条 Seed 字节未变）。
- 规则 ID：`competency_profile_id=python-backend-junior-v1`；规则版本：`profile_version=1.0.0`。
- 六道 Seed 均为 `review_status=draft`；两级均为 `status=pending`、`reviewer_role=owner`、`checked=[]`、`at=null`；`review_record_id=null`。来源记录的审核 ID 也是 null。
- 2026-10-06：助手已实际通过阅读工具读取下列官方 URL 及相应正文，形成原创转述与定位。**读过来源 ≠ Level 1 通过 ≠ Level 2 通过 ≠ 规则已审核 ≠ 岗位已批准。**
- 2026-10-06：本地后端 **613 passed / 2 deselected**，前端 **107 passed**，TypeScript/Vite 构建通过；实际 fixture 浏览器已验证导入后未审阻断、测试库显式批准后五题复盘、撤销后新场阻断/旧场冻结，以及改一字即更换规则摘要并回到未审。均不构成本人审核或 live 模型质量证明；运行记录见 `runtime/multi-role-current/verification.json`、`process.md` §69。
- 配套合成简历：`docs/demo/python-backend-nagasaki-soyo-resume.txt`，姓名长崎素世；简历不是现实身份或实绩证明，也不在知识包内。
- 合成 JD：包内 `examples/jd.txt`，manifest 已显式声明 `example_jd_file`，开头为 `SYNTHETIC_DEMO_JD`。不是企业原公告；不用简历反推要求。
- 直接上传发行物：执行 `make knowledge-pack PACK=knowledge_packs/python_backend_junior` 生成 `dist/knowledge-packs/python-backend-junior-1.0.1.zip`；同一目录内容重复构建字节相同，ZIP 根为 manifest/competencies/sources/NOTICE/seeds/examples，没有额外外层目录。导入时服务端会按本包规则试抽取示例 JD，六条要求逐一映射到六个能力。
- ZIP SHA256：`785e81d64b77047bf5695ceee116a6ac18b7e5a23bcc97bdfb397f35e9b68d33`；包实际 `content_digest=sha256:6ab03d0eddc710733a5389f5390eb6365238eafe84cbfec818066e7bd6f454a1`；规则 `profile_digest=sha256:fc575eba1be946bc10c1860d11f86a91780f3ff2148cdd88146e4bdb80369890`（规则字节未变，与 1.0.0 相同）。ZIP 字节 hash、规范化包摘要、规范化规则字节摘要用途不同，不可互换。
- 配套可上传 PDF：[`长崎素世_Python后端实习简历.pdf`](../demo/长崎素世_Python后端实习简历.pdf)，两页；实际 pypdf 提取 2218 字符，姓名、合成标识与末项项目可读取，未出现 U+0000/U+FFFD。材料不代表真人身份或技术实绩。

本材料只是可读审核入口，不能成为自批准记录。最终负责人登记应在包外同时绑定以上精确 `content_digest`、`competencies.json` canonical bytes SHA256、上述规则 ID/版本、本人完成的两级与规则核对事实，以及批准 Seed 的字节 hash。修改任何材料后应以新导入结果重算，不沿用本文旧值。不要修改包内 draft 为 approved 来绕过审核，避免批准/摘要循环；包外登记允许批准精确的 draft Seed 字节范围。

## 2. Level 1｜规则与材料边界（待哥哥本人）

### 2.1 有限声明式结构

`competencies.json` 仅包含 ID/version、中文 labels、关键词数组和空的 `seed_family_rules`。六个能力 ID 不重复，规则引用与 Seed 均指向已声明能力；这是一份作者编写的数据说明，不是已执行校验结论。没有代码、表达式、正则、远程执行入口或自批准字段。`seed_family_rules=[]`：**不从一个能力推导另一能力，不借 family 绑定无关技术题。**

关键词走项目既有大小写规范与字面子串匹配，**JD 首条匹配优先**。数据不表达否定、熟练程度、词边界、职责归属、项目真实性或多标签语义。不得把有限匹配叫作“完整语义理解”。JD 规则顺序为：SQL 参数绑定 → SQL 事务 → asyncio → 测试/异常 → HTTP → Python 可变性。更专门的要求放前；同一行混合要求只会按首条命中归类，应拆成独立要求再由人核对，不能假称六类都会命中。

### 2.2 实际规则清单

下表逐行对应数据数组；英文关键词在包中使用小写。能力 label 仅用于展示，不新增另一份业务状态源。

| 能力 ID / label | JD 关键词 | 直接证据关键词 | 相关上下文关键词 |
|---|---|---|---|
| `python.data.mutability` / Python 数据与可变性 | python 基础；python 数据结构；可变默认参数；浅拷贝；深拷贝 | 可变默认参数；浅拷贝；深拷贝；对象别名；列表共享 | python；数据处理 |
| `backend.http.api` / HTTP API 语义 | http api；http 接口；rest api；restful；状态码 | http api；http 接口；状态码；post /；get / | fastapi；后端接口；web 服务 |
| `backend.sql.transactions` / SQL 事务边界 | sql 事务；数据库事务；事务边界；提交与回滚 | 数据库事务；事务回滚；事务提交；with con；begin immediate | sqlite；数据库；数据存储 |
| `backend.sql.parameter_binding` / 参数绑定与 SQL 注入 | 参数绑定；sql 注入；sql注入；参数化查询 | 参数绑定；参数化查询；sql 注入；sql注入；占位符绑定 | sqlite；数据库查询；搜索接口 |
| `python.asyncio.blocking` / asyncio 与阻塞边界 | asyncio；异步 io；阻塞调用；事件循环 | asyncio；事件循环；to_thread；阻塞调用 | 异步；文件读取；并发请求 |
| `backend.testing.error_boundaries` / 测试与异常边界 | 单元测试；异常边界；错误边界；unittest；pytest | 单元测试；异常边界；错误边界；assertraises；unittest；pytest | 回归；失败处理；输入校验 |

**“直接证据规则”只表示文本直接提及能力相关主题，不等于技术正确或本人独立完成。**相关上下文仅说明可以询问，不能升级为直接技术证明，更不能升级为 verified。简历和项目说明重复同一自述仍是一份来源；第三方官方资料证明语言/协议规则，不证明候选人会做。

### 2.3 关键词易误匹配与漏匹配边界

| 文本/情景 | 规则可能表现 | 本人审核需保留的边界 |
|---|---|---|
| “没有使用 pytest / 不熟悉 asyncio” | 含直接关键词 | 不处理否定；必须结合原引文核对，不判为已掌握 |
| “同学负责数据库事务，我只写页面” | 直接匹配事务 | 关键词不理解主体；核对个人贡献，不能把团队能力归本人 |
| “学习过 SQL 注入案例” | 直接匹配安全主题 | 学习、自述与已实现防护不同；可问机制，不证明系统安全 |
| “只写 Python 脚本 / 使用 FastAPI 默认模板” | 相关上下文匹配 | 单独 python/fastapi 不做可变性/HTTP 机制的直接证明 |
| “数据库”“SQLite”但没有事务/绑定叙述 | 多个相关上下文匹配 | 不等于掌握事务和参数绑定，不借 family 补技术题资格 |
| “异步通知”“并发请求” | 可能相关匹配 | 不是 asyncio 事件循环证据；需澄清运行时和阻塞点 |
| “测试报告”“模型测试”“用户测试” | 不在直接关键词中，可能漏匹配 | 避免裸“测试”；没有命中不能自动判不会，允许用户澄清 |
| “python基础”“HTTPAPI”“SQL事务”“async IO”不同空格/写法 | 可能漏匹配，取决于精确登记关键词 | 不伪称全面同义归一化；正式 JD 可拆行并人工核对，不动态执行新规则 |
| `post /` 出现在教程代码引用或路径字符串 | 直接匹配 HTTP | 字面匹配没有词法上下文；引用不证明接口设计经验 |
| `with con` 出现在更长变量名或非 sqlite3 示例 | 直接匹配事务 | 子串不验证实际连接类型、事务配置与版本 |
| 同一要求“HTTP API、数据库事务与参数绑定” | 参数绑定首条优先 | 不生成其他能力已覆盖的结论；配套 JD 已按要求拆行 |
| “回归/输入校验/失败处理” | 相关匹配测试能力 | 不等于测试已执行、有断言或覆盖所有失败路径 |

以上边界是规则设计的已知限制，不是本轮测试结果。负责人若改变关键词、顺序或 label，应更新 profile_version/包版本并重新绑定摘要与规则审核；不能沿用旧批准解释新规则。

## 3. Level 2｜已读取的官方 primary sources（待哥哥本人）

所有来源登记在 `sources.json`。Python 页面读取时标题为 **Python 3.11.17 documentation**，URL 固定 `/3.11/`；不要跳到 `/3/` 当前版后混用 API。SQLite 页面是在线文档，未给出具体引擎发行版，采用页面更新时间定位，不能宣称它就是项目运行库版本。RFC 9110 是 June 2022 的 STD 97。未存档官方原始页面字节，故 `content_sha256=null`；阅读器文本不是原始字节快照。

| 代号 / source_id | 官方链接与版本 | 已读取的正文定位 |
|---|---|---|
| P1 `python311_default_arguments` | [Python 3.11 默认参数](https://docs.python.org/3.11/tutorial/controlflow.html#default-argument-values)，页面标题 3.11.17 | §4.8.1；“default values are evaluated at the point of function definition”；“evaluated only once”；`L=[]` 累积与 `L=None` 示例 |
| P2 `python311_copy` | [Python 3.11 copy](https://docs.python.org/3.11/library/copy.html)，3.11.17 | 导言赋值建立 bindings；shallow copy 插入 references；deep copy 递归 copies；“may copy too much” |
| H1 `rfc9110_http_semantics` | [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html)，STD 97 / June 2022 | §9.2.1 安全；§9.2.2 幂等/非幂等重试；§9.3.3 POST；§15.3.2–3 201/202；§15.5.1/5/10 400/404/409；§15.6.1 500 |
| T1 `sqlite_transactions` | [SQLite Transaction](https://www.sqlite.org/lang_transaction.html)，页面更新 2026-02-18 11:56:50Z | §2 显式事务；§2.1 多读单写；§2.2 IMMEDIATE/BUSY；§2.3 COMMIT 失败仍活动；§3 错误可能仅撤销当前语句 |
| T2 `python311_sqlite_transactions` | [Python sqlite3 连接上下文](https://docs.python.org/3.11/library/sqlite3.html#sqlite3-connection-context-manager)，3.11.17 | How to use the connection context manager：正常提交/未捕获异常回滚，不开事务/不关连接；[Transaction control](https://docs.python.org/3.11/library/sqlite3.html#transaction-control)：isolation_level 与隐式 DML 事务 |
| S1 `python311_sqlite_placeholders` | [Python sqlite3 值绑定](https://docs.python.org/3.11/library/sqlite3.html#sqlite3-placeholders)，3.11.17 | How to use placeholders：拼接注入示例；execute 第二参数；qmark 序列长度、named 字典键；`params=(1972,)` |
| S2 `sqlite_expression_parameters` | [SQLite Expressions / Parameters](https://www.sqlite.org/lang_expr.html#parameters)，页面更新 2026-08-14 19:21:30Z | §4：“placeholder in the expression for a value that is filled in at runtime”；不将值占位符等同于任意 SQL 结构替换 |
| A1 `python311_asyncio_tasks` | [Python 3.11 asyncio Tasks](https://docs.python.org/3.11/library/asyncio-task.html)，3.11.17 | Coroutines：“simply calling a coroutine will not schedule it”；Running in Threads / to_thread：同步阻塞示例、GIL 限制；Task Object：“cooperative scheduling” |
| U1 `python311_unittest` | [Python 3.11 unittest](https://docs.python.org/3.11/library/unittest.html)，3.11.17 | Basic example；TestCase.assertEqual；TestCase.assertRaises：指定异常通过、其他异常 error、无异常失败，exception 属性；TestCase.subTest |
| E1 `python311_exceptions` | [Python 3.11 异常](https://docs.python.org/3.11/tutorial/errors.html#handling-exceptions)，3.11.17 | §8.3：类型/基类匹配、未匹配传播、specific exceptions 建议、记录后 re-raise；§8.4 重新抛出示例 |

版权边界：仅登记官方链接/定位并原创中文转述，不把整份官方文档放进发行包；引用片段仅用于查找。原站许可见各官方页面及包内 NOTICE。来源内容需要哥哥本人重新核对，助手没有批准权。

## 4. 每题逐点来源定位、评分与外推边界

下列完整 Seed 文件名均以 `seed_python_backend_` 开头，位于包内 `seeds/`。所有技术要点均登记非空 reference_ids；可接受替代方案单列为工程策略，不借空来源宣布技术事实。通用 `*_evidence` Rubric 是表达/证据边界策略，不声称官方语言文档验证个人项目。

### 4.1 `seed_python_backend_python_mutability`

目标能力：Python 数据与可变性。题面为默认标签列表与嵌套拷贝的假设代码。

| point_id | 逐点依据 / 定位 | 允许结论与边界 |
|---|---|---|
| `rp_mut_default_once` | P1 §4.8.1，一次求值及累积示例 | 省略参数时共享已创建默认对象；不声称 Python 禁止所有可变默认值 |
| `rp_mut_none_sentinel` | P1 `L=None` / `if L is None` 示例 | 按调用新建默认列表；空列表与缺省区分是基于示例的 API 设计推导 |
| `rp_mut_copy_boundary` | P2 导言/浅深拷贝区别与 copy-too-much | 赋值不复制、浅拷贝共享成员；不承诺 deepcopy 任意资源都可复制 |
| `rp_mut_explicit_contract` | 原创可接受工程策略，非官方事实 | 可按所有权选择原地修改/有限复制，不强制深拷贝 |

评分：`*_mutable_default` 对应 P1；`*_copy_boundary` 对应 P2；不能仅因没背 API 扣分。危险信号是“每次新默认对象”“浅拷贝隔离所有层级”；至多一次 detail/counterfactual 追问，要求解释两次调用或一个内层变更。说明共享、None 哨兵与层级后停，不伪造代码实测输出。

### 4.2 `seed_python_backend_http_api_semantics`

目标能力：HTTP API 语义。题设包含创建成功但响应丢失，不从丢失响应推断未写入。

| point_id | 逐点依据 / 定位 | 允许结论与边界 |
|---|---|---|
| `rp_http_safe_read` | H1 §9.2.1 safe methods 与 GET 删除反例 | 客户端预期只读，附带日志不破坏 safe 定义 |
| `rp_http_created` | H1 §9.3.3、§15.3.2–3 | POST 创建后的 201/Location 是 SHOULD；202 不是已完成，不改成所有 POST 必须 201 |
| `rp_http_error_states` | H1 §15.5.1/5/10、§15.6.1 | 400/404/409/500 各自语义；实际业务映射需契约，404 也可用于不披露存在性 |
| `rp_http_idempotency` | H1 §9.2.2 intended effect、response might differ 与 non-idempotent retry | 幂等不是返回值相同，POST 不自动安全重试；不说 POST 绝不可能有幂等业务语义 |
| `rp_http_dedupe_design` | 原创可接受工程策略 | 请求标识/持久化结果/确认原结果；不声称 RFC 9110 定义 Idempotency-Key 或 exactly-once |

评分：`*_method_status` 对应安全/POST/状态章节；`*_retry_effect` 对应 §9.2.2 与明确的业务策略边界。危险信号是“所有失败都成功”“超时证明未执行”；至多一次 counterfactual/detail 追问丢响应情景。未验证去重实现记未知，不替候选人添加已上线保证。

### 4.3 `seed_python_backend_sql_transaction_boundary`

目标能力：SQL 事务边界。明确题设 Python 3.11、SQLite、isolation_level=DEFERRED、同库两次 INSERT。

| point_id | 逐点依据 / 定位 | 允许结论与边界 |
|---|---|---|
| `rp_tx_same_boundary` | T1 §2；T2 Transaction control 非 None 的隐式 DML 事务 | 两次写留在同连接/同事务是工作单元要求的工程推导；不能先 commit 再声称原事务整体回滚 |
| `rp_tx_context_manager` | T2 connection context manager 正常/异常/no-op/Note | with con 不开新事务/不关连接，且须让失败被正确看见；不能套用 3.12+ autocommit 属性 |
| `rp_tx_error_not_automatic` | T1 §3 Response To Errors | 某些错误只撤销当前语句，不能一概假定整事务已回滚 |
| `rp_tx_single_writer` | T1 §2.1–2.3 | 多读单写、BUSY 与 COMMIT 失败仍活动；不套用其他数据库锁/隔离默认值 |
| `rp_tx_verify_failure` | 原创可接受工程策略 | 显式控制或正确配置上下文，注入第二步失败并检查残留；没有声称运行通过 |

评分：`*_atomic_work_unit` 对应 T1/T2 事务范围与上下文；`*_failure_contention` 对应 T1 错误/竞争章节。危险信号是提前提交、吞异常后以为必回滚；至多一次反例/detail 追问真实退出路径。不能把补删伪装成原事务原子性，也不要求实现跨服务回滚。

### 4.4 `seed_python_backend_sql_parameter_binding`

目标能力：参数绑定与 SQL 注入。假设代码只在本地授权情景讨论，不执行真实目标攻击。

| point_id | 逐点依据 / 定位 | 允许结论与边界 |
|---|---|---|
| `rp_bind_no_interpolation` | S1 注入示例与 parameter substitution | 固定 SQL 与独立值分离；f-string 不等于驱动参数绑定 |
| `rp_bind_parameter_shape` | S1 qmark/named 要求与 `(1972,)` 示例 | 序列长度/字典键及单值元组；不跨驱动强推格式 |
| `rp_bind_value_not_identifier` | S2 §4 参数定义为表达式中的运行时值 | 参数不能当任意列名/关键字替换是语法边界推导，已在 statement 标明；不把该推导冒充原文逐字结论 |
| `rp_bind_allowlist` | 原创可接受工程策略 | 固定有限映射或不提供动态排序；不声称官方有该业务白名单 |
| `rp_bind_probe_inputs` | 原创可接受验证方案 | 单引号、注入形状值、非法排序；不把用例列表当安全实测 |

评分：`*_binding_values` 对应 S1；`*_structural_boundary` 对应 S2 及有限结构策略。危险信号是 f-string 自带安全、参数当列名或任意拼 sort；至多一次 detail/counterfactual 核对值与结构。参数绑定不证明授权、密码存储或所有查询整体安全。

### 4.5 `seed_python_backend_asyncio_blocking_boundary`

目标能力：asyncio 与阻塞边界。症状是题设，不是候选人真实性能记录。

| point_id | 逐点依据 / 定位 | 允许结论与边界 |
|---|---|---|
| `rp_async_cooperative` | A1 Task Object cooperative scheduling | 同一事件循环 Task 协作执行；不把 async def 当自动让出或 CPU 并行保证 |
| `rp_async_blocking_io` | A1 Running in Threads 的 blocking_io/time.sleep/gather 示例及 Coroutines 的 asyncio.sleep 示例 | 同步 IO/睡眠阻塞循环；to_thread 可卸载同步 IO；不声称所有库均线程安全 |
| `rp_async_thread_gil` | A1 to_thread Note 的 GIL 与例外 | 通常针对 IO，释放 GIL 扩展/其他实现有例外；不外推 free-threaded 默认行为 |
| `rp_async_called_not_scheduled` | A1 Coroutines 调用不自动调度，Task Object 调度语义 | 协程对象要 await/调度；create_task 不消除内部同步阻塞是调度规则推导 |
| `rp_async_measure_plan` | 原创可接受验证方案 | 心跳/受控并发观察其他任务；没有延迟、吞吐或加速比实绩 |

评分：`*_cooperation_io` 对应协程/调度/线程示例；`*_thread_boundary` 对应 to_thread Note。危险信号是 async/create_task 万能非阻塞、线程必加速 CPU；至多一次 detail/counterfactual 追问调度机会或运行时假设。未知资源线程安全与未测性能须保留，不给出虚假指标。

### 4.6 `seed_python_backend_testing_error_boundary`

目标能力：测试与异常边界。parse_limit 的 1–100、ValueError 和保存 OSError 是显式题设契约。

| point_id | 逐点依据 / 定位 | 允许结论与边界 |
|---|---|---|
| `rp_test_result_assertion` | U1 assertEqual、subTest 与 Basic example | 值断言/参数定位；“只调用不足以证明结果”是测试设计推导 |
| `rp_test_expected_exception` | U1 assertRaises 定义与 exception 属性 | 预期异常通过、不同异常 error、无异常失败；不以吞任意异常代替断言 |
| `rp_test_exception_scope` | E1 §8.3 类型匹配/传播与 specific exception/re-raise 建议 | 具体处理预期异常，意外错误不能假成功；不禁止在正确边界捕获并处理异常 |
| `rp_test_cases` | 原创可接受用例策略 | 正常/边界/非法/存储失败；pytest 等等价方法可接受，不要求固定 API 名词 |
| `rp_test_layer_mapping` | 原创可接受分层策略 | 输入映射、意外失败传播或明确上层处理；HTTP 状态与错误正文不是 Python 语言规定 |

评分：`*_case_assertions` 对应 U1 与明确业务测试策略；`*_exception_boundary` 对应 E1。危险信号是无断言或吞所有异常报成功；至多一次 detail/counterfactual 问一个非法值或存储失败。用例提出不等于执行、覆盖率或生产无错保证。

### 4.7 六题共同评分约束

每题两条技术 Rubric 权重分别为 2、1，另有权重 1 的 `*_evidence`，每条等级 0–3。技术 0 级只描述**已作答且经澄清确认的错误主张**；跳过、没问到、缺经历、明确未知不自动进入零分。证据评分区分题设、本人自述、官方技术事实与尚未执行的验证计划，不因缺量化指标普遍扣分。每条 red_flag 的 requires_followup 恒为 true，仅触发核对；max_followups=1，不持续诱导到“标准答案”。不得给招聘结论或用关键词判断现实履历真假。

## 5. 待哥哥本人登记的审核表

此表均为待办入口，没有预填 passed、签名、时间或审批记录。

| 对象 | Level 1：schema/source/能力/事实边界/追问意图 | Level 2：逐点来源与评分结论 | 规则审核 / 批准 |
|---|---|---|---|
| competencies profile 1.0.0 | pending，待哥哥本人核对 ID/引用/大小写/顺序/有限结构 | pending，待哥哥本人核对误匹配与禁止外推 | pending，未批准 |
| python_mutability | pending，owner | pending，owner；P1/P2 | 未批准 |
| http_api_semantics | pending，owner | pending，owner；H1 | 未批准 |
| sql_transaction_boundary | pending，owner | pending，owner；T1/T2 | 未批准 |
| sql_parameter_binding | pending，owner | pending，owner；S1/S2 | 未批准 |
| asyncio_blocking_boundary | pending，owner | pending，owner；A1 | 未批准 |
| testing_error_boundary | pending，owner | pending，owner；U1/E1 | 未批准 |
| SYNTHETIC_DEMO_JD 与长崎素世简历 | pending，合成标识与个人贡献/未知边界 | pending，不混为技术独立证据或真人履历 | 未批准为真实材料 |

负责人步骤：

1. 先看实际格式与规则校验报告，不用本文代替运行结果；确认导入只从 unreviewed 开始且不可选择，不触碰真实业务库。
2. 对本页六题逐点打开官方 URL 核对事实、版本、推导与可接受替代方案，尤其检查 SQLite/Python 默认事务配置和 HTTP SHOULD 的措辞。
3. 显式核对关键词顺序、直接/相关分离、否定/主体/子串误匹配边界、空 family 与六题能力引用；新规则不得借历史种子审核自动获批。
4. 若需更改材料，先改数据、更新版本与正文，再重新计算精确摘要和 Seed hash；不沿用先前内容的批准。
5. 只有哥哥本人完成 Level 1、Level 2 **以及规则审核**后，才通过项目包外审核 CLI 以 owner 身份显式登记核对事实与精确批准范围；CLI 所需确认不可代填。可以拒绝或部分批准，未批 Seed 仍不可评分。
6. 本人登记后，由集成负责人核对列表/详情的审核事实、规则摘要与新场次门禁；“格式通过”或“来源 URL 存在”仍不等于该步骤已完成。

当前结论：**完整材料与直接导入 ZIP 已交付，本地离线/fixture 浏览器验证通过；负责人本人两级与规则审核均 pending，第二岗位 live 质量未验证。**
