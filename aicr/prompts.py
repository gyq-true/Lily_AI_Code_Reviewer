"""提示词构造与审查重点定义。"""

from __future__ import annotations

FOCUS_LABELS = {
    "correctness": "正确性（逻辑、边界条件、并发）",
    "security": "安全性（注入、权限、敏感信息、依赖风险）",
    "performance": "性能（复杂度、I/O、内存）",
    "style": "代码风格与可读性",
    "bestPractice": "最佳实践与可维护性",
    "testing": "测试覆盖与可测性",
}

SEVERITY_LABELS = {
    "critical": "严重",
    "major": "重要",
    "minor": "一般",
    "suggestion": "建议",
}

VALID_SEVERITIES = ("critical", "major", "minor", "suggestion")

REPORT_SCHEMA_EXAMPLE = """{
  "summary": "对代码的总体评价（2-4 句话，中文）",
  "score": 0到100的整数，表示代码质量评分,
  "highlights": ["做得好的点，字符串数组"],
  "issues": [
    {
      "severity": "critical | major | minor | suggestion 之一",
      "title": "问题标题（简洁）",
      "line": 问题所在行号（无法确定则填 null）,
      "description": "问题详细描述（说明原因和潜在影响）",
      "suggestion": "具体改进建议",
      "code": "修复后的示例代码（如适用，否则为 null）"
    }
  ],
  "recommendations": ["进一步改进建议，字符串数组"]
}"""


def build_system_prompt(
    language: str,
    focus_list: list[str],
    is_diff: bool = False,
    kb_context: str = "",
) -> str:
    focus_lines = "\n".join(f"- {FOCUS_LABELS.get(f, f)}" for f in focus_list) or "- 整体代码质量"
    diff_note = (
        "\n注意：用户提供的是 git diff 补丁，只审查变更的部分（+ 行），"
        "结合上下文行理解意图，line 字段填新文件中的行号。" if is_diff else ""
    )
    kb_note = (
        f"\n\n# 项目规范上下文（知识库检索）\n{kb_context}\n"
        "请据此校验：代码是否违反上述项目规范、架构模式或编码标准，"
        "并在对应 issue 中引用相关规范。"
        if kb_context
        else ""
    )
    return f"""你是一位资深软件工程师与代码审查专家，精通多种编程语言、架构设计和安全最佳实践。

用户会提供一段 {language or '未知语言'} 代码，请你以专业、严谨、可操作的态度进行审查。审查重点：
{focus_lines}{diff_note}{kb_note}

# 审查输出要求
请按照以下 JSON 结构返回审查结果（不要输出任何 JSON 以外的内容）：

{REPORT_SCHEMA_EXAMPLE}

# 评分标准参考
- 90-100：优秀，几乎无可挑剔
- 80-89：良好，有少量可优化点
- 70-79：一般，存在明显可改进的地方
- 60-69：较差，存在较多问题
- 60以下：很差，存在严重问题

# 审查纪律
1. 每条 issue 必须真实存在，不要编造问题；严重等级要与影响匹配。
2. 优先指出 critical/major 级别的真实缺陷（如空指针、注入、资源泄漏、无限循环、明显逻辑错误）。
3. line 字段尽量精确到行号。
4. code 字段给出简洁可读的示例修复代码。
5. 全部使用中文回答。"""


def build_user_prompt(code: str, filename: str | None, language: str | None) -> str:
    fence_lang = (language or "").replace("`", "")
    return (
        f"文件名：{filename or '粘贴的代码'}\n"
        f"语言：{language or '未知'}\n\n"
        f"```{fence_lang}\n{code}\n```\n\n"
        "请按照系统要求返回 JSON 格式的审查结果。"
    )


def extract_json(text: str) -> dict | None:
    """从模型输出中安全提取 JSON，容忍 ```json 围栏包裹。"""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if "```" in candidate:
        parts = candidate.split("```")
        for part in parts[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                candidate = part
                break
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json_loads_safe(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            pass
    try:
        parsed = json_loads_safe(candidate)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


def json_loads_safe(text: str):
    import json

    return json.loads(text)
