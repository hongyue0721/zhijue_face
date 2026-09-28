"""显式能力配置（CompetencyProfile）注册表。

背景（主文件 R03）：JD 关键词映射、候选人直接/相关证据映射与 RTOS 家族
借用规则原本散落在 `domain/requisition.py`、`application/requisition.py`
与 `domain/questions.py` 的模块常量里，它们是**嵌入式岗位的实现事实**，
不是可从任意包数据里学习出来的通用机制。本模块把这些常量收拢为显式、
可注册的配置对象：

- 服务端注册表只登记已实现并通过回归的 profile（本轮唯一：`embedded-junior-v1`）。
- 知识包内的 `competencies.json` 只是声明镜像；服务端逐字段与注册表比对，
  不一致即拒绝。包不能借声明文件改写关键词规则或伪造能力覆盖。
- 未知 profile 明确返回不支持，绝不套用嵌入式关键词去处理其他职业。
- 配置只承载有限数据结构：关键词列表、ID 引用、家族前缀映射。不含脚本、
  动态 import、模板执行或任意正则规则引擎。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 规则元组形状与原模块常量保持一致（先封装、后接入，避免同时重写抽取与
# 选题算法；语义差异见各字段注释）。
KeywordRule = tuple[tuple[str, ...], str]
FamilyRule = tuple[str, str]


class CompetencyProfileError(ValueError):
    """profile 注册/比对失败：携带机器可读 code，不降级为默认配置。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Capability:
    competency_id: str
    label: str


@dataclass(frozen=True)
class CompetencyProfile:
    profile_id: str
    profile_version: str
    capabilities: tuple[Capability, ...]
    # JD 文本 → competency：首次匹配生效（顺序即优先级）。
    jd_keyword_rules: tuple[KeywordRule, ...]
    # 候选人材料直接证据（明确自述/排障经历）→ competency。
    direct_evidence_rules: tuple[KeywordRule, ...]
    # 相关上下文（如涉及 TIM/状态机）→ competency；严禁升级为直接证据。
    related_context_rules: tuple[KeywordRule, ...]
    # Seed 精确匹配之外的家族借用：root competency 槽可借用
    # target_prefix 前缀下未被占用的 approved Seed（原 RTOS 规则）。
    seed_family_rules: tuple[FamilyRule, ...]

    @property
    def competency_ids(self) -> frozenset[str]:
        return frozenset(capability.competency_id for capability in self.capabilities)

    def as_declared_dict(self) -> dict[str, Any]:
        """与包内 competencies.json 的声明结构做逐字段规范化比对时使用的形态。"""
        return {
            "competency_profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "capabilities": [
                {"competency_id": c.competency_id, "label": c.label}
                for c in self.capabilities
            ],
            "jd_keyword_rules": [
                {"competency_id": comp, "keywords": list(keywords)}
                for keywords, comp in self.jd_keyword_rules
            ],
            "direct_evidence_rules": [
                {"competency_id": comp, "keywords": list(keywords)}
                for keywords, comp in self.direct_evidence_rules
            ],
            "related_context_rules": [
                {"competency_id": comp, "keywords": list(keywords)}
                for keywords, comp in self.related_context_rules
            ],
            "seed_family_rules": [
                {"root_competency": root, "target_prefix": prefix}
                for root, prefix in self.seed_family_rules
            ],
        }


# embedded-junior-v1：常量逐条来自已验收实现，顺序与匹配语义不得变化。
# jd_keyword_rules 原为 domain/requisition._COMPETENCY_RULES。
_EMBEDDED_JD_RULES: tuple[KeywordRule, ...] = (
    (("c 程序", "c 语言", "c语言", "基础 c", "指针", "内存"), "embedded.c.basics"),
    (("中断", "nvic", "isr"), "embedded.mcu.interrupt"),
    (("uart", "串口", "dma"), "embedded.peripheral.uart_dma"),
    (("spi", "i2c", "can", "总线"), "embedded.peripheral.serial_bus"),
    (
        ("rtos", "freertos", "任务", "共享资源", "任务间通信"),
        "embedded.rtos.fundamentals",
    ),
    (("git", "版本控制", "回归"), "engineering.tooling.version_control"),
    (("本人工作", "个人贡献", "团队", "主要负责"), "project.ownership"),
    (("验证方法", "验证", "测量", "定位", "调试"), "engineering.verification"),
)

# 原 application/requisition._DIRECT_EVIDENCE_KEYWORDS。
_EMBEDDED_DIRECT_EVIDENCE_RULES: tuple[KeywordRule, ...] = (
    (
        ("c 程序", "c 语言", "c语言", "基础 c", "指针", "结构体", "位运算", "内存"),
        "embedded.c.basics",
    ),
    (("中断", "nvic", "isr", "exti"), "embedded.mcu.interrupt"),
    (("uart", "串口", "dma", "错帧", "波特率"), "embedded.peripheral.uart_dma"),
    (("spi", "i2c", "ic", "can", "总线"), "embedded.peripheral.serial_bus"),
    (
        (
            "rtos",
            "freertos",
            "任务",
            "队列",
            "queue",
            "互斥",
            "mutex",
            "信号量",
            "semaphore",
        ),
        "embedded.rtos.fundamentals",
    ),
    (
        ("git", "cmake", "版本管理", "版本控制", "回归"),
        "engineering.tooling.version_control",
    ),
    (
        (
            "主要负责",
            "负责",
            "个人项目",
            "分工",
            "团队完成",
            "本人",
            "我负责",
            "个人贡献",
        ),
        "project.ownership",
    ),
    (
        (
            "示波器",
            "逻辑分析仪",
            "调试",
            "排查",
            "定位",
            "复现",
            "联调",
            "消抖",
            "测量",
            "验证",
        ),
        "engineering.verification",
    ),
    (("linux", "驱动"), "embedded.linux.basics"),
)

# 原 application/requisition._RELATED_CONTEXT_KEYWORDS。
# TIM/定时器/状态机只标识验证价值，绝不证明已掌握 interrupt/NVIC/ISR。
_EMBEDDED_RELATED_CONTEXT_RULES: tuple[KeywordRule, ...] = (
    (("tim", "定时器", "输入捕获", "状态机", "周期任务"), "embedded.mcu.interrupt"),
)

# 原 domain/questions._RTO_FUNDAMENTALS / _RTO_FAMILY_PREFIX。
_EMBEDDED_FAMILY_RULES: tuple[FamilyRule, ...] = (
    ("embedded.rtos.fundamentals", "embedded.rtos."),
)

EMBEDDED_JUNIOR_V1 = CompetencyProfile(
    profile_id="embedded-junior-v1",
    profile_version="1.0.0",
    capabilities=(
        Capability("embedded.c.basics", "C/嵌入式基础"),
        Capability("embedded.mcu.interrupt", "中断与 NVIC"),
        Capability("embedded.peripheral.uart_dma", "UART/DMA 排障"),
        Capability("embedded.peripheral.serial_bus", "SPI/I2C/CAN 串口总线"),
        Capability("embedded.rtos.fundamentals", "RTOS 基础与并发"),
        Capability("embedded.rtos.queue", "RTOS 队列机制"),
        Capability("embedded.rtos.synchronization", "RTOS 同步与互斥"),
        Capability("embedded.rtos.scheduling", "RTOS 任务调度与周期"),
        Capability("embedded.linux.basics", "嵌入式 Linux 基础"),
        Capability("engineering.tooling.version_control", "版本控制与回归"),
        Capability("project.ownership", "个人贡献边界"),
        Capability("engineering.verification", "调试与验证方法"),
    ),
    jd_keyword_rules=_EMBEDDED_JD_RULES,
    direct_evidence_rules=_EMBEDDED_DIRECT_EVIDENCE_RULES,
    related_context_rules=_EMBEDDED_RELATED_CONTEXT_RULES,
    seed_family_rules=_EMBEDDED_FAMILY_RULES,
)

# 服务端注册表：本轮唯一经回归验证的能力配置。新增 profile 必须伴随
# 审核、映射实现与验收，不是由上传包自行登记。
PROFILE_REGISTRY: dict[str, CompetencyProfile] = {
    EMBEDDED_JUNIOR_V1.profile_id: EMBEDDED_JUNIOR_V1
}


def get_registered_profile(profile_id: str) -> CompetencyProfile:
    profile = PROFILE_REGISTRY.get(profile_id)
    if profile is None:
        raise CompetencyProfileError(
            "COMPETENCY_PROFILE_UNSUPPORTED",
            f"能力配置 {profile_id} 未在服务端注册；本轮仅支持 "
            + ", ".join(sorted(PROFILE_REGISTRY))
            + "。不会用其他职业的关键词规则兜底。",
        )
    return profile


def match_registered_profile(declared: dict[str, Any]) -> CompetencyProfile:
    """把包内 competencies.json 声明与注册表逐字段比对。

    声明不能扩充或改写规则：任何差异（包括关键词顺序、label 文案）都拒绝，
    避免“同一 profile_id、不同语义”的两套真相。
    """
    profile_id = declared.get("competency_profile_id")
    if not isinstance(profile_id, str):
        raise CompetencyProfileError(
            "PACK_PROFILE_INVALID", "缺少 competency_profile_id"
        )
    profile = get_registered_profile(profile_id)
    canonical = profile.as_declared_dict()
    if declared != canonical:
        raise CompetencyProfileError(
            "PACK_PROFILE_MISMATCH",
            f"competencies.json 与服务端注册的 {profile_id} 规则不一致；"
            "能力配置以服务端实现为唯一真源。",
        )
    return profile
