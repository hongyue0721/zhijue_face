# UI-59 五页前端重构交接

## 2026-09-22 UI-59 更新（优先于上文旧布局描述）

按负责人审图和页面批注，初始上传改为居中的单张卡片；识别中用真实请求状态驱动扫描动画，减少动态效果时静止。事实列表仅展示采用/不采用二选滑块，初始无选择，不自动采用；更正独立弹窗。选择后才出现提交栏，操作成功后收起状态；部分事实已确认仍可继续准备，空资料和失败资料仍可管理/删除。

岗位为连续表单，可选分区折叠；面试突出当前问题与回答，次要控制折叠；复盘为题目导航与正文；简历为纸面与来源栏。减少重复卡片、装饰性小字和常驻动作，保留真实失败、来源、确认和重试门禁。上传卡片允许轻阴影与 16px 圆角。

后续页继续按同一规则收敛：计划就绪、等待作答、草稿状态等可由当前内容直接判断的标签不再常驻；Planner/Seed 明细不进入用户流程；总分直接排版，报告限制默认折叠；JD 与回答字符计数只在达到上限 80% 后显示。处理中、失败、重试、来源核对、确认和打印仍由真实业务状态控制。

负责人明确要求移除模式徽章、fixture 提示条和文件要求说明，作为本轮界面规则覆盖旧版全局明示要求。后端 run_mode/data_mode/readiness 不变，不自动切模式；服务不可用仍显示真实错误。验收环境模式由测试记录说明，不将 fixture 结果当生产模型结果。

- 已完成资料、准备、面试、复盘、简历五页渐进式布局；上传单卡片居中，识别仅在真实等待期间播放 JS 动画，支持 reduced-motion。二选滑块初始不选中，更正独立；提交栏仅有选择时出现，成功状态和已完成生成按钮收起。保留部分事实已确认时的继续入口，以及空/失败资料的管理和删除入口。
- 前端测试 25/25、TypeScript 和 Vite build（118 modules）通过。本轮不改后端；§58 后端结果是历史证据，不冒充重跑。
- 真实 HTTP + 隔离 SQLite/openJiuwen + synthetic fixture 完成上传、确认、五题/一次追问、报告、优化、简历确认与打印门禁；Knowledge/回答失败经刷新和显式重试恢复。1366/375 五页无页面横向溢出；扫描动画普通模式 2 个、reduced-motion 0 个。证据 runtime/ui-59/verification.json 与 responsive-results.json。发现报告导航挤压后改为编号/分数一行、题目另行。
- 5204/8040 是界面验收 fixture，未调用外部模型。负责人上传材料被模拟抽取结果来源校验拒绝：不能据此认定材料有问题；未读取或重处理私人材料、未绕过来源校验。任意真实 PDF 的生产抽取不在本次 fixture 证据范围。真实模型质量、生产 Knowledge 和负责人最终验收 NOT_RUN；状态 IMPLEMENTED，非 ACCEPTED。

负责人随后在 5199 live 第 4 题遇到一次 `UPSTREAM_FAILED`：Answer 正文完整持久化，但现场私密配置仍是此前验收用的 `MODEL_MAX_RETRIES=0`，服务端据此写入 `retryable=false`，前端只能显示到达上限。本轮把该 live 配置恢复为受限默认 `MODEL_MAX_RETRIES=2`，并让 Operation 读取与 retry 接口共同按当前预算重判既有回答的 `UPSTREAM_FAILED / UPSTREAM_TIMEOUT`。页面现在只保留一张失败提示和“重试分析”按钮；点击只创建 parent-linked 分析 Operation，复用原 Answer，累计总尝试仍硬限制为三次。浏览器只读复验按钮已出现，没有代替负责人点击，外部模型调用新增 0 次。

本次自动回归：后端非 live **326 passed / 2 deselected / 96 warnings**；Ruff **80 files**；前端 **25/25**、TypeScript 与 Vite build（118 modules）；规范 **47/47**。8004 readiness 为 live/configured，旧失败 Operation 的只读视图为 `retryable=true`。

API、数据库、依赖、模型配置无变化。当前未提交工作区保留既有修改；改动前快照在仓库外 output/frontend-refactor/pre-refactor-worktree.tar.gz。负责人可在 5204 审阅视觉；真实材料抽取需单独使用已授权的 live 环境，不在 fixture 中伪造成功。
