# 前端重构交接

基线：`85d4b1f5630be12af798f0aad3da3052baec91dc`。

负责人已授权本轮重构。代码与交互验收以交付包中的 AGENTS.md、TEST_REPORT.md、status.json 和 evidence 为准。此前状态与截图保留为历史，不把新增前端运行声明成业务模型 live 验收。

迁移时先合并源码与明确后端解析修改，再运行目标工具链并同步 api.md、process.md 和 UI 契约。不能跳过网络结果不明、失败恢复和长文本场景。
