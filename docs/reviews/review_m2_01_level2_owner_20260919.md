# Seed Level 2 负责人审核记录

- `review_record_id`：`review_m2_01_level2_owner_20260919`
- 决策日期：2026-09-19
- 审核者角色：`owner`
- 决策来源：负责人在当前施工会话中明确选择“六条全部通过并批准”
- 审核范围：`docs/level2-review-packet-m2-01.md` 中六条 Seed 的技术事实、官方来源、平台作用域、允许 claim 与禁止外推边界
- 来源证据：`runtime/evidence/m2-01-level2/source-manifest.json`（ignored，本地官方 PDF URL、版本、字节数与 SHA-256）
- 结论：六条 Level 2 均 `passed`，进入 approved demo bank

## 批准条目

| seed_id | 被审核内容版本 | 批准后版本 | Level 2 | review_status |
|---|---:|---:|---|---|
| `seed_embedded_freertos_queue_mechanism` | 0.2.0 | 0.2.1 | passed | approved |
| `seed_embedded_rtos_task_period` | 0.2.0 | 0.2.1 | passed | approved |
| `seed_embedded_mutex_vs_semaphore` | 0.2.0 | 0.2.1 | passed | approved |
| `seed_embedded_uart_dma_debug` | 0.2.0 | 0.2.1 | passed | approved |
| `seed_embedded_spi_i2c_selection` | 0.2.0 | 0.2.1 | passed | approved |
| `seed_embedded_interrupt_priority` | 0.2.0 | 0.2.1 | passed | approved |

`0.2.1` 仅记录负责人审核状态和本审核记录 ID；题干、reference points、red flags、rubric 与平台边界保持负责人审阅的 0.2.0 内容不变。

## 已确认的修正与边界

- Queue 使用手册实际的固定 item-size 复制语义，并明确任务 API 与 `FromISR` API 的阻塞边界。
- 周期任务区分相对延时与绝对唤醒，tick 分辨率有 S24 来源，不写死唯一 tick 配置。
- Mutex/Semaphore 只使用 S24 明确的所有权、优先级继承、配置与 queue set 边界，不保留无原文支撑的 `lessen/minimize` 归因。
- UART/DMA 与 SPI/I2C 同时覆盖 F4/RM0090、G4/RM0440、H7/RM0433；寄存器位名、DMA 映射、清除顺序和 I2C 速率不得跨系列外推。
- 中断优先级以 PM0214 的 Cortex-M4 架构规则为主，G4 的 102 通道只作为型号实例，不外推到 F4/H7。
- red flag 只触发追问，不自动扣分；UNKNOWN 仍不等于不会。

## 批准后的门禁

- `config/demo.yaml` 的 `live_allowed_review_status=approved` 保持不变；后端 `SeedBank` 只向 `live_only=True` 返回 approved 条目。
- 本批准只覆盖这六条 Seed，不授权扩到 24 条，不批准新平台/新版本来源外推，也不等于 M3/M4 已实现或验收。
- 任何 reference point、来源版本、平台范围、rubric 或题干实质变化都必须提升 Seed 版本并重新审核；不得沿用本记录静默放行。
- 本次未运行真实候选人回答、业务 LLM 或评分链；这些属于 M3/M4 行为验证，不伪装成本审核已覆盖。
