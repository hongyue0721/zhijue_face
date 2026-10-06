# 2026-10-03｜竞赛工作区验收记录

## 结论与被测版本

功能实现完成；本地离线与实际浏览器已有通过证据。**不宣称最终版本全新资料 live 端到端、目标国产系统兼容或负责人验收通过。** 源码发行物必须由独立解包回执确认，不由本文预签名。

- 文档审查基线：`d91023ac10cd50a78d766284f05300b2e817b120`。
- 恢复会话核对的实际 HEAD：`d1b217f49d1c22e31ded623d5a00305ca1c1e5ec`；工作区有未提交修改，按实际代码继续，未回退、reset、stash 或覆盖既有变更。本轮未提交或推送。
- 被测对象是该 HEAD 加工作区；关键代码 SHA256、UTC 时间、模式、输入标识、24 项布局测量及真实状态证据在 [verification.json](evidence/2026-10-03/verification.json)。最终发行物以包外 SHA256 和逐文件 manifest 精确标识。
- 当前运行环境：Linux `7.2.7-arch1-1`、x86_64；Python 3.11.16、openJiuwen 0.1.18。SDK 锁定兼容 commit 的事实不等于官方新发行版。

## 实际改动

| 范围 | 文件与行为 |
|---|---|
| 资料与事实一致性 | `application/profiles.py`、`adapters/db/profiles.py`、`StartPage.tsx`：创建响应与组合视图保持同一资料/revision，旧响应不能抢回档案；Snapshot 激活与确认事务一致 |
| 出题与冻结 | `application/interviews.py`、`domain/questions.py`、`application/knowledge_packs.py`：主问题去重与能力主题保留；幂等重放校验显式输入；受理冻结包内容及实际审核范围；今天的撤销不改写旧场次 |
| 包信任与可用性 | 六条内置审核内容固定历史 hash；新版导入不更换默认 release；列表/详情实际复核存储完整性，损坏项直接显示不可用；ZIP 普通目录合法但路径/类型/大小/声明限制不放松 |
| 恢复与清理 | `application/operations.py`、`adapters/db/operations.py`、`application/content_generation.py`、`adapters/knowledge.py`：链尾重试、累计预算、原答原题绑定、失败后重启恢复；部分索引失败也清理本次写入 |
| 六页小范围集成 | `KnowledgePacksPage.tsx`、导入对话框、准备页、报告/简历入口及 `storage.ts`：导入失败持久恢复；资料/JD 上下文往返；按钮按真实生成能力门禁；报告窄屏五题换行，不隐藏后三题 |
| 运行与发行 | `scripts/demo.sh`、`scripts/manage_knowledge_pack.py`、Makefile、CI 与 `scripts/verify_bundle.sh`：显式库选择、配置路径、启动超时与进程组清理；doctor/`write_checksums.py`/打包共享当前存在的源码清单，未提交删除不恢复、新源码不漏包；规范检查默认只写 runtime，不覆盖已签名源码报告；独立安装/检查/fixture HTTP 验证，不只验 checksum |
| 模型契约 | `adapters/model.py`：允许的技术引用来自已审 `rubric_snapshot.reference_ids`，解释点 `point_id` 不是来源 ID；不放宽引用与事实语义校验 |
| 文档与契约 | `api.md`、`docs/ui-contract.md`、数据/Workflow/Knowledge 文档、README、运行手册、CHANGELOG、process 同步；新增 `c91f8b34d602` 审核快照迁移；OpenAPI 与当前 DTO 对齐 |

没有第二套岗位 Knowledge、全局激活接口、职业范围扩张、基座替换或给上传包自动批准的通道。

## 命令与结果

| 验证 | 实际执行位置/命令 | 结果 |
|---|---|---|
| 后端离线 | `services/api`：`.venv/bin/python -m pytest tests -q -m 'not integration_live'` | exit 0；**476 passed、2 deselected、109 warnings** |
| Ruff | `services/api`：`.venv/bin/ruff check src tests smoke migrations`；`.venv/bin/ruff format --check src tests smoke migrations` | exit 0；96 文件已格式化 |
| 前端回归 | `apps/web`：Node 24 环境执行 `pnpm test` | exit 0；4 文件、**44 passed** |
| 前端构建 | 同目录 `pnpm build` | exit 0；TypeScript + Vite，122 modules |
| 迁移 smoke | SQLite backup API 复制自建 synthetic 库；实际 `alembic downgrade a7c4e1f29b58` → `upgrade head` | exit 0；到 `c91f8b34d602`；1 Profile / 3 Interview / 1 Report 的 ID 保留，FK 检查无异常；重新升级的 3 个旧审核快照均 null |
| 浏览器 | 实际 Chromium 驱动六页；不是组件测试替代品 | 四尺寸 24 项通过，所有记录无横向页面溢出/按钮横向出界；报告第 5 题实际选择成功 |
| 三份不同资料 | 自建 fixture HTTP：UART 排障、FreeRTOS Queue、TIM 状态机；normal/skip/end | 5 根完整 / 1 根 skipped 且 score=null / 提前结束 4 根 unmeasured 且总分 null；模型/embedding 调用 0 |
| 并发包导入 | 同一新内容以两个不同命令并发 POST、观察真实 Operation | 一个 release；一次新登记、一次 reused；默认内置 release 不变；仍 unreviewed |
| 源码库存回归 | `test_bundle_source_inventory.py`：真实临时 Git 索引内已删文件、未跟踪 Unicode 源码及被忽略 runtime，实际生成 checksum 和 ZIP 并核对内容摘要 | 修复前 FileNotFoundError；修复后 exit 0、1 passed；删除不恢复、运行数据不打包、manifest 与实际字节一致 |
| 发行源码不可变回归 | `test_spec_check_in_extracted_bundle_preserves_source_integrity`：实际 ZIP 解包、运行规范 CLI、用原清单 `sha256sum -c CHECKSUMS.sha256` | 修复前 exit 1；修复后 PASS；两项发行回归共 2 passed，不以刷新清单掩盖源码变动 |
| 源码发行验证 | `make competition-bundle` 后 `make verify-bundle` | 结果、被测 ZIP SHA256、退出码与完整日志记录在包外 `dist/bundles/*.verification.json`；本文不提前填写 PASS |

warnings 包括上游 SDK/Pydantic/Agent 弃用提示和故意构造的 ZIP 重复项；没有用 skip、降低评分/语义门槛或吞异常使回归通过。远端 CI 没有推送或触发。

## 浏览器验收与截图

四尺寸：1440×900、1366×768、1024×768、390×844。保留浅色与蓝色主操作，未重写五页。

- F01/F11：六页测量；报告手机端原横向轨道会藏住第 3–5 题，已改为原控件两列换行，四尺寸复查通过；含 HTML 字符的长包名、64 位摘要和来源展开不破版。
- F02：真实响应尚未返回时显示“正在读取岗位知识包列表”，不显示空列表/0 数量；隔离空包库仍能导入；传输失败明确显示“无法连接服务”，不是空态。
- F03/F04：可用、unreviewed、rejected、内容损坏的状态来自 API；损坏项 `validation_status=failed/selectable=false`，真实 `storage_integrity` 失败明细可追溯；不改写历史审批记录。
- F05：已受理导入关闭/刷新继续用 Operation ID 恢复；失败错误保留；只有 succeeded 且有效 release 才完成；不可重试错误要求换修正文件。
- F06/F07：准备页未提交的多行 JD 和展开字段在站内往返保留；正文仅存当前 JS 内存，刷新会清空，不写持久存储；新计划冻结的包不被新导入或页面选择修改。
- F08：Esc 关闭与焦点回到“导入岗位包”实际验证；dark/reduced-motion 偏好下仍为白底、深色文本。
- F09：延迟真实详情响应后快速切换，最终详情和 release 标识仍是当前选项。
- F10：资料确认、准备、面试作答/受控结束、报告/优化、accepted 简历及打印均有实际页面证据；fixture 缺生成器时明确禁用，不把 fixture 成功冒充生成。
- B11：实际上传带 `<img ... onerror=alert(...)>` 包名的合成包，界面作为纯文字显示；插入图片 0、alert 0；来源只有 http(s) 主动链接、`noopener noreferrer nofollow`，自动来源请求 0。javascript URL 拒绝另有解析器回归。

可携带的合成截图：

- [正常 live 桌面报告](evidence/2026-10-03/live-report-desktop.png)
- [正常 live 手机报告，五题均可见](evidence/2026-10-03/live-report-mobile.png)
- [真实模型回答优化](evidence/2026-10-03/live-coaching.png)
- [已确认简历实拍](evidence/2026-10-03/accepted-resume.png)
- [真实损坏 release 被阻断，fixture](evidence/2026-10-03/fixture-corrupt-release.png)
- [真实空包库，fixture](evidence/2026-10-03/fixture-empty-list.png)

本机另保留 `runtime/competition-accept/current-live-ui.mp4`（4 分 56.8 秒，1440×900）和 `current-live-resume-print.pdf`（实际打印输出，2 页）。录屏仅为本轮页面回放，不是从空库开始的全新上传演示；runtime 与私密 env 不进入源码发行包。

## Live：成功、复用、失败分别记录

### 成功证据范围

1. `full-live-diagnostic.json`：2026-10-03 15:26:14–15:34:28 UTC，synthetic 输入；真实 openJiuwen + qwen3.8-flash + SiliconFlow BAAI/bge-m3（1024 维），抽取、确认、索引、五题/两次追问、83 分完整报告、回答优化、简历生成均取得通过结果。**该次使用临时诊断包装，不能代替最终正常 launcher 的验收。** 索引回执记录 14 个 embedding logical calls，不把 logical calls 写成精确 HTTP 调用总数。
2. `current-profile-live.json`：15:41:09–15:47:10 UTC，正常 launcher、无诊断包装；复用前项未改变的已确认 BGE-M3 索引资料，五根题、两次追问、87 分/5 根 scored、五条优化建议 ready。两次分析失败通过原答、parent-linked、累计预算内重试成功，没有重发一份新回答。
3. 简历生成请求按既有业务目标去重复用同快照同目标的 **accepted 草稿**，没有重新调用模型。初版 smoke 把 accepted 当非法状态，原证据 `status=failed` 和错误保留，不改成 passed。永久 `smoke/demo.py` 现接受 draft/accepted，但仍检查所有确认 claim 绑定。
4. `current-profile-reuse-verification.json`：15:49:54 UTC，仅只读/幂等核对已 ready 的优化与 accepted 草稿，status=passed；**不重测抽取或新生成**。页面已经实际显示对应报告、优化、草稿与打印结果。

已知成功 usage：正常 coaching 1851 input / 7095 output / 8946 total；诊断 resume 1081 / 1500 / 2581。失败调用 usage、所有费用以及精确总 HTTP 调用数缺乏完整计量，记录 null；不估造费用或把未知写成 0。评分 Report 的 prompt_versions/model_fingerprint/sdk_version 部分仍为未登记值，不能凭生成链元数据倒填成已记录。

### 不能删掉的失败与未验证项

- `full-live-final.json`：正常 launcher 全新上传在 15:37:12 UTC 失败，`UPSTREAM_FAILED`，P-EXTRACT 未通过事实来源校验；没有候选事实假成功。
- `full-live-final-recovered.json`：明确重新选择同一 synthetic 文件后，第二个独立导入在 15:39:52 UTC 失败，`UPSTREAM_FAILED`，模型服务请求失败。不是第二次事实校验失败，也不是后台无限重试。
- **最终版本“全新上传 → 确认 → 真索引 → 五题 → 优化 → 新简历 → 确认打印”仍 NOT_RUN/待重新验收。** 既有资料成功链、accepted 复用、诊断链、fixture 和构建均不能替代它；继续真实请求需遵守负责人当前模型预算与材料授权。

## 主文件验收矩阵对应

| ID | 已有证据与边界 |
|---|---|
| A01–A06 | doctor 假工作区、来源漂移、脱敏与缺私密配置回归；launcher fixture 剥离 ambient 配置；CI 范围已同步。干净发行物的当前安装结果见包外回执，不宣称远端 CI 已跑 |
| B01–B10 | `test_knowledge_pack_contract.py` / `test_knowledge_pack_security.py` / `test_knowledge_packs_api.py` 的解析、安全、归一摘要、冲突与不可用半包回归 PASS；六条已审 Seed 逐 hash 与历史批准基线一致，内容差异 0，只有包目录迁移 |
| B11 | 恶意文本实际浏览器 PASS；不安全 URL 解析器拒绝 PASS |
| C01–C09 | 审核外置、摘要绑定、能力配置拒绝、Seed 批准范围、候选 DTO 隔离和空库管理回归/真实 fixture PASS；不批准新上传包 |
| D01–D09 | `test_knowledge_pack_freeze.py`、计划幂等/恢复及迁移回归 PASS；真实新版导入后默认计划仍冻结内置 digest；损坏内容明确失败、不借默认替代；旧审核快照保持 null |
| E01–E09 | 导入幂等/链尾预算/恢复回归及实际关闭刷新 PASS；当前并发新内容只登记一个 release。SSE/polling 的恢复契约有回归，不把隔离断流/超时写成生产错误实测 |
| F01–F11 | 上述实际 Chromium 场景及 24 项测量 PASS；不是 TypeScript/Vite 的视觉结论 |
| G01/G02 | 三份不同 synthetic 资料及 normal/skip/end 的真实 fixture HTTP PASS |
| G03/G04 | 原答保留与预算内 retry 实际 live PASS；引用/事实来源门槛回归及真实不合法输出拒绝 PASS |
| G05 | 诊断完整链、正常已确认资料链与复用证据分别成立；最终正常全新上传验收**未通过/待重验**，不能总记 PASS |
| G06/G07 | 未授权真实材料 NOT_RUN；隔离错误注入有回归，但当前生产 429、完整费用/调用计量 NOT_RUN |
| H01/H02 | 必须以最终 ZIP 的包外独立验证回执为准，排除 env/runtime/.git/缓存并实跑 fixture；不是历史包校验结果 |
| H03 | NOTICE 与第三方来源登记保留；完整赛事再分发许可审查 NOT_RUN，不擅自许可全部内容 |
| H04 | 负责人真实业务库迁移 NOT_RUN；仅自建 synthetic 副本迁移 smoke PASS |
| H05/H06 | 当前 openEuler/UOS/麒麟/国产 CPU 复验 NOT_RUN；2026-09-22 openEuler 容器 fixture 记录保持原范围，不外推 native/live |
| H07 | 正式匿名参赛材料及官方规则复核 NOT_RUN；本轮证据仅合成材料，无学校/教师资料导出 |
| H08 | 当前 README/API/界面/源码按实际行为同步；正式参赛材料与负责人最终验收 NOT_RUN |

## 迁移与回滚

新增 `c91f8b34d602` 在 `a7c4e1f29b58` 后仅给 interview 增加可空 `pack_review_snapshot`。旧记录不补造历史批准范围；旧报告读路径保留，无法证明旧绑定时不继续生成依赖它的新题。

操作仅针对明确选择、获授权的库：

1. 停写并确认只有一个业务 worker；SQLite backup API 或等价一致性备份同时保存业务库、知识索引及岗位 release 存储。只复制正在写的 `.db` 而遗漏 WAL 不是可用备份。
2. 在隔离副本先复验。手工迁移示例：

   ```bash
   export ZHIJUE_DATABASE_URL='sqlite:////absolute/isolated/business.db'
   services/api/.venv/bin/alembic -c services/api/alembic.ini upgrade head
   ```

3. 本轮 smoke 实际对自建 fixture 副本执行了 downgrade 到 `a7c4e1f29b58` 再 upgrade 到 `c91f8b34d602`，业务 ID 与 FK 保持；丢失的历史审核快照重新升级后仍是 null，不能凭当前审核补回。
4. 回滚首选停写后恢复**同一时点备份和匹配的旧程序版本**。只回退本次迁移可在隔离副本执行 `alembic ... downgrade a7c4e1f29b58`，但会删除冻结审核快照；重新升级无法恢复这些事实。继续回到 `e62a9f8c10bd` 还会删除岗位包表和绑定列，不能宣传为无损回滚。当前程序不能直接接已降级 Schema。
5. 不对负责人真实 runtime 执行迁移、降级或清理。本轮自建实例与临时副本和真实业务数据隔离。

## 演示路径与待验收

- 离线状态演示：`make demo-fixture` → 手填合成事实并确认 → 填合成 JD → 选择内置已审包 → 五题/skip/end → 真实服务生成的 fixture 报告。优化/简历入口按 `content_generation=absent` 禁用；用来展示状态机，不展示模型质量。
- 本机既有 live 页面回放：上述已确认资料、报告、优化、accepted 草稿与录屏可以复查；再次开启服务不会自动调用模型。重新作答/生成/上传属于新的真实请求，不因能看到页面就获得预算授权。
- 独立发行复现：`make verify-bundle` 在干净临时目录安装，跑离线与前端回归，再启动 fixture 经真实代理完成五根题；清理自己的服务和临时目录。
- Gate 6/7 未收口项：最终全新资料 live 闭环、指定 OS/架构、完整许可与匿名材料审查、负责人独立验收、远端 CI、公网/正式发行提交。没有把任一 NOT_RUN 改写成 PASS。
