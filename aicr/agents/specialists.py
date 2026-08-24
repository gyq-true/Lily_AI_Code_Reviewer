"""多 Agent 专项定义：总览 + 5 个专项审查专家，各自携带聚焦提示词。

每个专项只负责自己的领域，由 LangGraph 并行调度，最终由 synthesizer 合并。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..prompts import REPORT_SCHEMA_EXAMPLE


@dataclass(frozen=True)
class Specialist:
    name: str
    label: str
    focus_key: str | None  # 对应审查关注点 key；None 表示总览（始终运行）
    mission: str


SPECIALISTS: list[Specialist] = [
    Specialist(
        name="overview",
        label="总览与正确性",
        focus_key=None,
        mission=(
            "全面审查代码的正确性、逻辑边界、并发与整体质量，"
            "给出总体评分（score）、做得好的亮点（highlights）、进一步改进建议（recommendations），"
            "并在 issues 中记录正确性/逻辑类问题。"
        ),
    ),
    Specialist(
        name="architecture",
        label="架构与最佳实践",
        focus_key="bestPractice",
        mission=(
            "检查架构模式、分层是否合理、模块依赖、设计模式、命名与可维护性，"
            "对照项目规范上下文校验是否违反既定架构约定或最佳实践。"
        ),
    ),
    Specialist(
        name="security",
        label="安全",
        focus_key="security",
        mission=(
            "检查注入（SQL/命令/模板）、越权、敏感信息泄露、硬编码密钥、"
            "不安全反序列化、依赖漏洞、日志泄露等安全风险。"
        ),
    ),
    Specialist(
        name="performance",
        label="性能",
        focus_key="performance",
        mission=(
            "检查算法复杂度、冗余 I/O、N+1 查询、内存泄漏、不必要拷贝、"
            "缺失缓存、无界循环/递归等性能问题。"
        ),
    ),
    Specialist(
        name="style",
        label="风格与可读性",
        focus_key="style",
        mission=(
            "检查代码风格、可读性、命名、注释、重复代码、函数过长、"
            "魔法数字、嵌套过深等代码异味问题。"
        ),
    ),
    Specialist(
        name="testing",
        label="测试与可测性",
        focus_key="testing",
        mission=(
            "检查测试覆盖、可测性、边界与异常路径是否被测试覆盖、"
            "测试隔离、断言有效性、缺少回归测试等问题。"
        ),
    ),
]

SPECIALIST_BY_NAME: dict[str, Specialist] = {s.name: s for s in SPECIALISTS}


def select_agents(focus: list[str]) -> list[str]:
    """根据关注点选择运行的 agent。空 focus 运行全部。"""
    if not focus:
        return [s.name for s in SPECIALISTS]
    names = ["overview"]
    for f in focus:
        for s in SPECIALISTS:
            if s.focus_key == f:
                names.append(s.name)
    return list(dict.fromkeys(names))


def build_system(spec: Specialist, language: str, kb_context: str, is_diff: bool) -> str:
    diff_note = (
        "\n注意：用户提供的是 git diff 补丁，只审查变更的部分（+ 行），"
        "结合上下文行理解意图，line 字段填新文件中的行号。" if is_diff else ""
    )
    kb_note = (
        f"\n\n# 项目规范上下文（知识库检索）\n{kb_context}\n"
        "请据此校验代码是否违反上述项目规范、架构模式或编码标准，"
        "并在对应 issue 中引用相关规范。"
        if kb_context
        else ""
    )
    intro = (
        f"用户会提供一段 {language or '未知语言'} 代码。"
        "请只聚焦你的专业领域，不要越界审查其他方面（其他方面由其他专家负责）。"
    )
    return f"""你是一位资深软件工程师与代码审查专家，本次以「{spec.label}」专家身份参与协作审查。

{spec.mission}

{intro}{diff_note}
{kb_note}

# 审查输出要求
请按照以下 JSON 结构返回审查结果（不要输出任何 JSON 以外的内容）：

{REPORT_SCHEMA_EXAMPLE}

# 审查纪律
1. 每条 issue 必须真实存在，不要编造；严重等级要与影响匹配。
2. line 字段尽量精确到行号；code 字段给出简洁可读的示例修复代码。
3. 全部使用中文回答。"""
