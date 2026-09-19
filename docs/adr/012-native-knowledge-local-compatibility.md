# ADR-012｜原生 Knowledge 的本地兼容试验

状态：PROPOSED（负责人未标记 ACCEPTED）/ M0-03-DEL 技术验证 VERIFIED  
日期：2026-09-18；更新：2026-09-19  
关联：M0-03、R07/R16/R19、K04/K16/K20

## 决策目标

验证真实 `openjiuwen==0.1.18` 的 `SimpleKnowledgeBase` 是否能够在单机 Demo 上完成：文本解析、分块、真实 embedding、Milvus Lite 入库、带 provenance 检索、跨进程重启、删除及删除后重启确认。不得用同名本地 Knowledge、Mock 或自建检索替代比赛主链路。

## 已采用的最小组合

- Knowledge：`SimpleKnowledgeBase`。
- Parser / Chunker：SDK 自带 `TxtMdParser` / `CharChunker`。
- Store / Indexer：SDK 自带 `MilvusVectorStore` / `MilvusIndexer`，本地 Milvus Lite 文件、FLAT、cosine、dense。
- 版本：`openjiuwen 0.1.18`、`pymilvus 2.6.7`、`milvus-lite 3.2.1`、Python 3.11.16。
- Embedding：负责人指定 `BAAI/bge-m3`，经 SDK 自带 `OpenAIEmbedding` 调用 OpenAI-compatible `/v1` base；实测返回 1024 维。密钥只在 ignored `.env.local`，权限 0600。
- 数据：两个明确标记 synthetic 的 profile；没有外发 Demo Resume v1。

没有新增第三方包。原拟安装 CPU torch 并下载 BGE-small 的方案已被负责人指定的远程 BGE-M3 取代；旧失败日志保留，但不再重试或作为当前配置。2026-09-19 起 openJiuwen 的依赖来源从正式 0.1.18 wheel 临时改为固定 Git commit；这增加首次同步的 Git/网络要求，但不增加运行期组件。

## 实际通过的部分

2026-09-18 的 live 运行中，两个独立 KB 均完成：

1. 原生 `parse_files` 返回一个非空 Document，解析文本 hash 与本地合成源一致；不存在文件返回空集合后由探针明确判失败，未伪装成功。
2. 原生 `add_documents` 写入 Milvus Lite；重复 doc_id 被 SDK 拒绝。
3. 原生 `retrieve` 返回对应 profile 的 document_id、chunk_id、source_id 与 source_sha256；两个 KB 未串档。
4. 关闭第一进程后，在第二进程重新构造 Knowledge/Store/Indexer，仍检索到同一来源与内容 hash。
5. `BAAI/bge-m3` 请求名实际发送并返回 1024 维；网关内部模型映射没有独立厂商证明，因此只记录“请求模型名 + 实测维度”，不扩写成供应商背书。

原始阶段证据：`runtime/m0-03-live-20260918T172000/phase-ingest.json`、`phase-restart_check.json`；去敏汇总：`runtime/evidence/m0-03/knowledge-partial-20260918T172000.json`。

## 初始阻塞：删除返回值兼容（历史证据）

`SimpleKnowledgeBase.delete_documents` 真实调用 `MilvusIndexer.delete_index` 后，Milvus Lite 已把 profile A 的行数从 1 变为 0；但 `pymilvus 2.6.7` 为兼容旧 Milvus 行为，可在删除成功且返回主键时返回 `list`。openJiuwen 0.1.18 的 `delete_index` 对非 dict 结果执行 `int(result)`，因此发生：

```text
int() argument must be a string, a bytes-like object or a real number, not 'list'
```

框架随后返回删除失败，profile B 未继续删除，删除后重启检查为 `NOT_RUN`。因此“底层产生了删除效果”不能被包装成“Knowledge 删除 VERIFIED”。

该根因与 openJiuwen 官方尚未合入的 PR #1344 描述一致：PR 明确修复 Milvus delete 返回 list 时的 TypeError，并为 list/dict/int 返回形态补测试。[S21]

## 明确不采用

- 不修改 `.venv/site-packages`，不 monkeypatch SDK 私有方法。
- 不捕获框架失败后直接返回成功。
- 不用自建 SQLite/FTS 或同名类冒充 Knowledge。
- 不因为 profile A 实际行数为 0 就跳过 SDK 返回状态或删除后重启门槛。
- 不盲目切换 `pymilvus` 版本：2.6.8/2.6.9 已有本地 URI→db_name 兼容问题，且没有证据证明能解决 list 返回。

## 已选择的解除方案与实测

负责人本轮明确指示开始后，没有另造同名适配类，也没有提交重复 PR。施工采用以下可回退方案：

1. 在业务仓库外检出官方 `agent-core` tag `v0.1.18`。
2. 原样应用官方 PR #1344 的两个提交：代码只增加 `list/tuple → len(result)` 分支，测试只增加非空/空 list 两例。
3. 将该精确结果推送到公开兼容 commit `72c4985111b835530ec616f70dd67117eb2e015c`；相对官方 tag 仅 2 个文件、31 行新增。
4. 将 `pyproject.toml` 与 `uv.lock` 固定到该 commit；通过 `uv sync --frozen` 安装，不修改 site-packages。
5. 在现有 PR #1344 下提交真实 Milvus Lite 生命周期验证评论，不创建重复 PR。[S23]

实际结果：

- 未修复 v0.1.18 回归：1 failed / 1 passed，非空 list 返回 false。
- 修复后相同回归：2 passed；上游目标测试文件：21 passed。
- 补丁 worktree 四进程 live：四阶段全部通过，删除后重启 0 命中。
- 项目锁定依赖、清除 `PYTHONPATH` 后再次四进程 live：四阶段全部通过，删除后重启 0 命中。
- 安装后的 `MilvusIndexer` 源码 SHA256 为 `bf7214e3cdaaa13a1e2c3d5da6c1e2a7920cb90dd64fcad356c33d2328ca760d`，与验证 worktree 一致；`direct_url.json` commit 与锁文件一致。

因此 `config/demo.yaml` 的 Knowledge `delete_compatibility_verified` 与 `actual_compatibility_verified` 可设为 true，M0-03/M0-03-DEL 可标记 VERIFIED。这个结论只针对固定兼容 commit，不代表负责人 ACCEPTED，也不代表正式 0.1.18 wheel 已修复。官方发布包含修复后必须切回正式源并重跑 M0-02/M0-03。

## API 与依赖影响

- HTTP API / DTO / SSE / 业务数据库：无变化；`api.md` 无需修改。
- 直接依赖包：没有新增；保留 `pymilvus[milvus-lite]==2.6.7`。openJiuwen 来源由 PyPI wheel 临时改为公开 Git commit，首次同步需要 Git/网络，本地免费运行。
- 模型 usage/token/cost：初次部分验证 7 次、兼容验证两次 live 各 9 次，M0-03 累计 25 次成功逻辑 embedding 调用；准确 HTTP transport 尝试数 NOT_MEASURED，usage/token/cost 为 null。DeepSeek LLM NOT_RUN。
