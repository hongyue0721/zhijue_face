# 六条种子两级审核表（M2-01）

**状态：Level 1 与 Level 2 均已完成；六条 `review_status=approved`。**
作者 Agent 在 2026-09-19 完成 S24/S26/S28/S29/S30 正文核对与修正；负责人随后明确选择“六条全部通过并批准”。统一审核记录：[`review_m2_01_level2_owner_20260919`](reviews/review_m2_01_level2_owner_20260919.md)。

审核记录同时写进每条种子的 `review_levels` 字段（机器可校验），本表提供可读视图与逐条依据。

## Level 1：schema / 来源 / competency / 事实边界 / follow-up 与 intent 一致性

审查者角色：`self_check`（AI 自检，**不是**独立审核，也不冒充独立专家）。日期：2026-09-18。

| 种子 | schema | 来源可追溯 | competency 与岗位相关 | 事实边界 | follow-up 与 intent 一致 | 结论 |
|---|---|---|---|---|---|---|
| `seed_embedded_freertos_queue_mechanism` | 通过 | `freertos_reference_manual_v10` → S24 | embedded.rtos.queue | 不评价经历真实性；允许替代方案 | detail/counterfactual ↔ 追机制与边界 | passed |
| `seed_embedded_rtos_task_period` | 通过 | `freertos_reference_manual_v10` → S24 | embedded.rtos.scheduling | 不要求具体 tick 数值 | detail/counterfactual ↔ 追周期基准 | passed |
| `seed_embedded_mutex_vs_semaphore` | 通过 | `freertos_reference_manual_v10` → S24 | embedded.rtos.synchronization | 仅"加锁"不得判已掌握/未掌握 | detail/counterfactual ↔ 追保护范围 | passed |
| `seed_embedded_uart_dma_debug` | 通过 | `rm0090_stm32f4` / `rm0440_stm32g4` / `rm0433_stm32h7` → S28/S30/S26 | embedded.peripheral.uart_dma | F4/G4/H7 位名、DMA 映射与清除顺序不得互相外推 | detail/reflection ↔ 追可观察依据 | passed |
| `seed_embedded_spi_i2c_selection` | 通过 | `rm0090_stm32f4` / `rm0440_stm32g4` / `rm0433_stm32h7` → S28/S30/S26 | embedded.peripheral.serial_bus | F4 100/400 kHz 与 G4/H7 另列 1 MHz 的边界已显式保留 | detail ↔ 追选型约束 | passed |
| `seed_embedded_interrupt_priority` | 通过 | `pm0214_cortex_m4` / `rm0440_stm32g4` → S29/S30 | embedded.mcu.interrupt | M4 架构规则与 G4 通道数实例分离 | detail/counterfactual ↔ 追分组影响 | passed |

自检同时确认（由测试与校验器强制，不是人工口头保证）：

- 结构性检查（`tools/validate_spec.py`）：技术类参考要点缺 `reference_ids` 必被拒；`red_flag.requires_followup` 只能为 `true`；`approved` 必须两级 `passed`；`technical_review` 必须 Level 1 `passed`；`max_followups` 不得超 1。
- 可追溯性检查：种子的 `reference_id` 必须映射回 `docs/14-sources-and-rules.md` 已登记来源，悬空引用即失败（负向自检已实测会失败）。
- 业务加载检查（`tests/unit/test_seed_bank.py`）：当前六条 approved Seed 在 `live_only=True` 下全部可加载；降级为 technical_review/draft 时必须失败；混合题库只返回 approved 条目。

## Level 2：依据可靠技术资料审核 reference points

审查者角色：`owner`。**正式状态：passed；决策日期：2026-09-19。**

以下来源准备结果已由负责人整体确认；每条 Seed 已写入 `review_levels.level2` 的 `passed/owner/checked/at`：

| 种子 | 已定位的可靠来源与参考要点 | 来源准备结果 |
|---|---|---|
| queue | S24 FreeRTOS Chapter 3：复制固定 item-size 字节、收发阻塞超时、`FromISR` 无阻塞等待 | 修正 `"by copy, not by reference"` 的非逐字引述；新增 ISR 边界 |
| period | S24 Chapter 2/7：`vTaskDelay` 相对延时、`vTaskDelayUntil` 绝对唤醒/固定频率、tick 分辨率 | `rp_tick_resolution` 改为带 S24 引用的技术参考点 |
| mutex | S24 Chapter 4/7：ownership、binary semaphore/mutex 语义、优先级继承与 `configUSE_MUTEXES` | 删除手册未出现的 `"lessen/minimize"` 归因；保留已明确行为及 queue set 边界 |
| uart_dma | S28 RM0090 第 30 章、S30 RM0440 第 40 章、S26 RM0433 第 48 章：接收状态/错误、连续 DMA | 补齐 F4/G4 来源；寄存器位名、DMA 映射与清除顺序按系列隔离 |
| spi_i2c | S28 RM0090 第 27/28 章、S30 RM0440 第 39/42 章、S26 RM0433 第 47/50 章 | 补齐 F4/G4 来源；F4 的 100/400 kHz 与 G4/H7 另列 1 MHz 分开陈述 |
| interrupt | S29 PM0214 §2.3.5/§2.3.6；S30 RM0440 §14.1 | Cortex-M4 架构规则与 G4 102 通道实例分离，未向 F4/H7 外推 |

逐 reference point 摘要、允许 claim 与禁止外推边界见 `docs/level2-review-packet-m2-01.md`；下载快照 SHA-256 见 `runtime/evidence/m2-01-level2/source-manifest.json`。

Level 2 结论已写入每条 Seed；共同 `review_record_id` 指向上述负责人审核记录。

## approved 条件与当前结果

1. Level 1 与 Level 2 均 `passed`：已满足；
2. `review_record_id` 指向可定位的审核记录：已满足；
3. 负责人明确确认：已满足。

`config/demo.yaml` 的 `seed_bank.live_allowed_review_status=approved` 保持权威门槛；后端 `SeedBank` 读取该配置，当前六条均可进入 approved demo bank。该批准不授权扩到 24 条，也不代表 M3 live question 已实现或验证。
