<!-- derived_from_confirmed_facts: true -->
# 简历（嵌入式方向 · 合成演示材料）

## 技能
- 网关板用的 ESP32-S3 DevKitC-1，靠串口连实验室那台 STM32F411 主控
- 数据走 MQTT 协议发布到老师提供的 broker，QoS 选了 1
- 网关上我用 SPI 接口驱动了一块 0.96 寸 OLED 显示连接状态
- 自己做的 SSD1306 OLED 小项目：I2C 四线改写过一版，又换 SPI 七线重写了一遍
- 第二个项目是 CAN 总线采集系统，我写了 IAP 引导跳转那段 bootloader
- bootloader 调试用 ST-LINK 配 Keil，拿逻辑分析仪看 CAN 差分波形
- CANopen、以太网协议都只翻过教材，没实际用过
- FreeRTOS 只上过课，实验里建过任务用过队列，项目里没用过

## 项目
1. ESP32-S3 数据网关（2025 年秋季学期嵌入式课设，个人独立）
2. CAN 总线采集系统的 bootloader（2026 年春季学期实验室任务）
3. SSD1306 OLED 驱动重写（个人小项目）
