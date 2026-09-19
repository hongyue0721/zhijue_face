# Level 2 Review Packet（M2-01 六条种子）

**用途**：负责人或独立复核者逐条核对技术事实。作者 Agent 在 2026-09-19 完成来源下载、正文定位、平台边界核对与 claim 修正；随后负责人在当前会话中明确选择“六条全部通过并批准”。
**当前状态：六条 Level 2 全部 `PASSED`，`review_status=approved`。** 可追溯审核记录：[`review_m2_01_level2_owner_20260919`](reviews/review_m2_01_level2_owner_20260919.md)。该决定只覆盖本 Packet 的六条，不授权扩到 24 条。

来源均为官方文档；`source_location` 为手册页码/章节（非 PDF 物理页）。本轮下载快照与 SHA-256 记录在 `runtime/evidence/m2-01-level2/source-manifest.json`，平台作用域规则见 `docs/14-sources-and-rules.md`。这些本地快照只作可复核运行证据，不进入 Git。

---

## 1. `seed_embedded_freertos_queue_mechanism`

| 字段 | 内容 |
|---|---|
| competency | `embedded.rtos.queue` |
| reference_id | `freertos_reference_manual_v10` |
| source document | The FreeRTOS Reference Manual V10.0.0（官方 PDF） |
| source version / revision | Reference Manual for FreeRTOS version 10.0.0, issue 1（© 2017 Amazon.com, Inc.） |
| platform_scope | FreeRTOS 内核（内核无关机制） |
| version_scope | V10.0.0 手册；机制在 FreeRTOS 内核长期稳定 |
| Level 1 | passed（self_check，2026-09-18） |
| Level 2 | **PASSED**（owner，2026-09-19） |

| reference_point | source location | source excerpt / 精确事实摘要 | 允许支持的 claim | 不允许外推的边界 |
|---|---|---|---|---|
| `rp_queue_decouple` | Chapter 3 Queue API（3.16 `xQueueReceive`、3.22 `xQueueSend`） | `xQueueSend` 与 `xQueueReceive` 都定义 `xTicksToWait` 阻塞等待参数；前者等待可用空间，后者等待可用数据 | "任务可通过队列传递数据；生产者和消费者可独立阻塞并配置超时" | "解耦节奏"是由 API 语义得出的工程作用，不冒充手册逐字结论；不声称某移植层的具体 tick 行为 |
| `rp_queue_copy_semantics` | Chapter 3 Queue API（3.22 `xQueueSend`、3.16 `xQueueReceive`） | `xQueueSend` 参数说明：`pvItemToQueue` 指向待复制数据，队列创建时设定多少字节就复制多少字节；`xQueueReceive` 将该项复制到接收缓冲区 | "队列复制固定 item-size 字节；若 item 类型是指针，复制的是指针值" | 不把"指针值可作为 item"表述成队列自动管理被指向对象的生命周期 |
| `rp_queue_isr_boundary` | Chapter 3 Queue API（3.23 `xQueueSendFromISR`、3.17 `xQueueReceiveFromISR`） | `FromISR` 版本供中断上下文使用，且没有阻塞等待时间 | "ISR 应使用对应 `FromISR` API，不能在 ISR 中调用会阻塞等待的任务版操作" | 不外推具体端口的中断优先级限制；该限制需按移植文档另查 |
| `rp_queue_alt` | —（acceptable_alternative，无来源要求） | 替代方案（环形缓冲+信号量、流缓冲区/消息缓冲区）属工程选择 | "可接受替代方案，只要说明选择依据" | 不得声称替代方案等价于队列的全部语义 |
**建议核对入口**：S24 Chapter 3（3.16、3.17、3.22、3.23）。

---

## 2. `seed_embedded_rtos_task_period`

| 字段 | 内容 |
|---|---|
| competency | `embedded.rtos.scheduling` |
| reference_id | `freertos_reference_manual_v10` |
| source version / revision | V10.0.0 issue 1 |
| platform_scope | FreeRTOS 内核 |
| version_scope | V10.0.0 |
| Level 1 | passed ｜ Level 2 | **PASSED**（owner，2026-09-19） |

| reference_point | source location | 事实摘要 | 允许支持的 claim | 不允许外推 |
|---|---|---|---|---|
| `rp_delay_vs_delayuntil` | Chapter 2 Task and Scheduler API（2.10 `vTaskDelay`、2.11 `vTaskDelayUntil`） | 官方手册明确：`vTaskDelay` 指定的是相对于调用时刻的相对延时（relative delay/sleep time）；`vTaskDelayUntil` 指定的是任务下一次解除阻塞并执行的绝对唤醒时刻（absolute wake time） | "vTaskDelay 提供相对延时，vTaskDelayUntil 基于绝对时间点控制下一次唤醒，两者设计目标与时间基准不同" | 不声称两者的具体底层实现或在存在中断/高优先级抢占干扰时的理想精度 |
| `rp_drift` | 同上（2.11 `vTaskDelayUntil` 机制说明） | 官方手册明确指出 `vTaskDelayUntil` 的设计目的是实现固定频率周期执行（"execute periodically with a fixed frequency"）；在相对延时 `vTaskDelay` 循环中，由于循环体内的执行耗时与可能的调度等待，两次执行间隔会顺延，难以保证固定周期 | "若在周期循环中使用相对延时，任务执行耗时波动会影响周期的恒定性；固定频率周期任务建议使用基于绝对唤醒时刻的 vTaskDelayUntil" | 不使用"必然累积严重漂移"等过度断言（偏差程度取决于任务执行时间开销与抢占情况），不给出具体抖动数值 |
| `rp_tick_resolution` | Chapter 2（2.10 `vTaskDelay` 参数说明）与 Chapter 7（`configTICK_RATE_HZ`） | 延时单位为 tick；换算后的绝对时间取决于 tick 频率，最坏分辨率为一个完整 tick 周期 | "tick 粒度影响周期精度；具体 tick 频率属于配置策略" | 不声称某具体 tick 频率值为唯一标准，也不承诺硬实时精度 |
---

## 3. `seed_embedded_mutex_vs_semaphore`

| 字段 | 内容 |
|---|---|
| competency | `embedded.rtos.synchronization` |
| reference_id | `freertos_reference_manual_v10` |
| source version / revision | V10.0.0 issue 1 |
| platform_scope | FreeRTOS 内核 |
| version_scope | V10.0.0 |
| Level 1 | passed ｜ Level 2 | **PASSED**（owner，2026-09-19） |

| reference_point | source location | 事实摘要 | 允许支持的 claim | 不允许外推 |
|---|---|---|---|---|
| `rp_mutex_ownership` | Chapter 4 Semaphore API（4.1/4.2 二值信号量、4.6 `xSemaphoreCreateMutex`、4.12 `xSemaphoreGetMutexHolder`） | 官方手册将互斥量定义为带所有权（ownership）的特殊二值信号量：互斥量必须由获取它的同一任务释放（持有者可通过 `xSemaphoreGetMutexHolder` 查询），专用于共享资源互斥；二值信号量不带所有权，常用于任务间或中断与任务间的事件同步（可由不同上下文 Give） | "互斥量具有所有权语义，必须由持有任务释放；二值信号量无所有权，更适合同步" | 不声称递归互斥量细节（由 4.8 单独处理） |
| `rp_priority_inheritance` | Chapter 4（mutex API）与 Chapter 7（`configUSE_MUTEXES`） | mutex 包含优先级继承而 binary semaphore 不包含；高优先级任务等待同一 mutex 时，持有任务继承其优先级，归还 mutex 后解除继承；`configUSE_MUTEXES` 控制相关能力是否纳入构建。手册另明确 queue set 中的 mutex 不会触发持有者继承 | "mutex 具有优先级继承；可讨论它避免无界优先级反转的作用、配置条件和已列明的边界" | 手册没有承诺消除全部阻塞；不得省略临界区时长、持锁路径与 queue set 等边界后声称问题已彻底解决 |
| `rp_alternatives` | —（acceptable_alternative） | 临界区/单任务独占/消息传递等属工程替代方案 | "接受工程替代方案并说明适用条件" | 不声称替代方案无额外代价 |
---

## 4. `seed_embedded_uart_dma_debug` ★ F4/G4/H7 来源作用域已闭合

| 字段 | 内容 |
|---|---|
| competency | `embedded.peripheral.uart_dma` |
| reference_id | `rm0090_stm32f4`、`rm0440_stm32g4`、`rm0433_stm32h7` |
| source document | ST RM0090 Rev 22、RM0440 Rev 9、RM0433 Rev 8 |
| platform_scope | STM32F407；STM32G4（含 G431）；STM32H742/743/753/750 |
| version_scope | 各手册上述修订版 |
| Level 1 | passed ｜ Level 2 | **PASSED**（owner，2026-09-19） |

| reference_point | source location | 事实摘要 | 允许支持的 claim | 不允许外推 |
|---|---|---|---|---|
| `rp_receiver_flags` | RM0090 第 30 章、RM0440 第 40 章、RM0433 第 48 章 | 三个系列均定义接收就绪与接收错误状态；F4 使用 RXNE，G4/H7 按 FIFO 配置呈现 RXNE/RXFNE | "UART 接收链路有状态/错误位可作为排障证据" | 位名、FIFO 语义与清除顺序必须按目标系列解释 |
| `rp_dma_continuous` | RM0090 §30.3.13、RM0440 §40.5.19、RM0433 §48.5.19 | 三份手册分别提供 USART 与 DMA 连续通信小节 | "F4/G4/H7 均有 USART+DMA 连续通信配置路径" | 不跨系列复制 DMA 通道映射、缓冲与清除步骤 |
| `rp_overrun` | 同上各 USART 章节的状态/错误段落 | 三个系列均列出 overrun、noise、framing、parity 等接收错误 | "错误状态可用于定位偶发丢数据" | 不声称一次读标志即可唯一定位根因 |
| `rp_method` | —（acceptable_alternative） | 排查方法论属工程实践 | "接受最小化复现/缩小范围等排查路径" | 不把方法论包装成手册结论 |

**来源审核修正**：原版本只引用 H7，不能覆盖主演示 F407/G431。本轮已补 S28/RM0090 与 S30/RM0440，并把跨系列不一致的位名、DMA 映射与清除顺序写入事实边界。平台来源缺口已闭合，但 Level 2 结论仍由负责人作出。

---
## 5. `seed_embedded_spi_i2c_selection` ★ F4/G4/H7 来源作用域已闭合

| 字段 | 内容 |
|---|---|
| competency | `embedded.peripheral.serial_bus` |
| reference_id | `rm0090_stm32f4`、`rm0440_stm32g4`、`rm0433_stm32h7` |
| platform_scope | STM32F407；STM32G4（含 G431）；STM32H742/743/753/750 |
| version_scope | RM0090 Rev 22；RM0440 Rev 9；RM0433 Rev 8 |
| Level 1 | passed ｜ Level 2 | **PASSED**（owner，2026-09-19） |

| reference_point | source location | 事实摘要 | 允许支持的 claim | 不允许外推 |
|---|---|---|---|---|
| `rp_spi_mode` | RM0090 第 28 章、RM0440 第 42 章、RM0433 第 50 章 | 三个系列均定义 SPI 同步串行通信，并提供基于状态轮询或专用中断的管理方式 | "SPI 是同步串行通信，可用轮询或中断管理" | 不跨系列外推 FIFO 深度、DMA 映射或时钟上限 |
| `rp_i2c_speed` | RM0090 第 27 章、RM0440 第 39 章、RM0433 第 47 章 | 三者均使用 SDA/SCL；F4 手册列 Standard 100 kHz 与 Fast 400 kHz，G4/H7 手册另列 Fast-mode Plus 1 MHz | "速率能力具有系列边界；选型时需核对目标器件资料" | 不把 G4/H7 的 1 MHz 能力外推到本种子覆盖的 F4 |
| `rp_selection_criteria` | —（acceptable_alternative） | 选型标准属工程判断 | "按速率/拓扑/引脚/中断与 DMA 支持比较" | 不给出唯一正确答案 |

**来源审核修正**：原版本把 H7 的三档速率描述当作单一参考。本轮已补 F4/G4 来源，并显式保留 F4 仅列 100/400 kHz、G4/H7 另列 1 MHz 的差异。平台来源缺口已闭合，但 Level 2 结论仍由负责人作出。

---
## 6. `seed_embedded_interrupt_priority` ★ 已按架构级来源修正

| 字段 | 内容 |
|---|---|
| competency | `embedded.mcu.interrupt` |
| reference_id | `pm0214_cortex_m4`（**架构级**，适用 F407/G431） |
| source document | ST PM0214 Rev 10（Cortex-M4 MCUs and MPUs programming manual） |
| platform_scope | **Cortex-M4 / M4F 内核**（覆盖 F407、G431） |
| version_scope | PM0214 Rev 10 |
| Level 1 | passed ｜ Level 2 | **PASSED**（owner，2026-09-19） |

| reference_point | source location | source excerpt / 事实摘要 | 允许支持的 claim | 不允许外推 |
|---|---|---|---|---|
| `rp_nvic_priority_levels` | PM0214 §2.3.5 Exception priorities（手册 p.41） | 原文：*"Configurable priority values are in the range 0-15"*；*"A lower priority value indicating a higher priority"* | "Cortex-M4 可配置优先级范围为 0-15（4 位，16 级），数值越小优先级越高" | **不得外推到 Cortex-M7（H7）或 M0**；也不得给出某型号的中断通道总数 |
| `rp_nvic_channel_count_scope` | RM0440 第 14 章 14.1 NVIC main features（手册 p.436，G4 实例） | 原文：*"102 maskable interrupt channels"*、*"16 programmable priority levels (4 bits of interrupt priority are used)"*、*"refer to the PM0214 programming manual for Cortex®-M4"* | "G4 侧 NVIC 有 102 个可屏蔽中断通道、16 级优先级，并明确引用 PM0214" | **102 是 G4 数值，不是 F4/H7 的数值**；H7 为 150（RM0433 19.1），两者不得互换 |
| `rp_grouping` | PM0214 §2.3.6 Interrupt priority grouping（手册 p.41） | 原文：优先级寄存器分为 *"group priority"* 与 *"subpriority within the group"* 两个字段；*"Only the group priority determines preemption"*；同组同子优先级由硬件索引决定顺序 | "分组决定抢占：只有组优先级决定抢占，子优先级只决定同组内处理顺序" | 不给出分组的具体实现寄存器名以外的细节；不外推到其它内核 |

**说明**：本种子原先只引 `rm0433_stm32h7`（H7，150 通道）。按负责人 2026-09-18 决策 §3，已改引 **S29（Cortex-M4 架构级）** 作为优先级范围与分组依据，并用 **S30（G4）** 作为平台实例。这样 F407/G431 主演示岗位的事实有正确来源。

---

## 汇总

| seed | Level 1 | Level 2 | 审核结论依据 |
|---|---|---|---|
| queue | passed | PASSED | S24 正文已定位；修正 copy 语义措辞并补 ISR 边界 |
| period | passed | PASSED | S24 正文已定位；tick 分辨率改为技术参考点 |
| mutex | passed | PASSED | S24 正文已定位；删除无原文支撑的 "lessen/minimize" 归因，保留手册明确行为与边界 |
| uart_dma | passed | PASSED | 已补 S28/S30，F4/G4/H7 作用域缺口闭合 |
| spi_i2c | passed | PASSED | 已补 S28/S30，并显式区分 F4 与 G4/H7 速率能力 |
| interrupt | passed | PASSED | S29 架构级规则 + S30 G4 实例已定位 |

**负责人结论**：六条事实、来源和边界全部通过并批准。Seed 已写入 `review_levels.level2.status=passed`、`reviewer_role=owner`、日期与统一 `review_record_id`；批准后版本为 0.2.1。后续任何实质内容或来源范围变化必须提升版本并重新审核。
