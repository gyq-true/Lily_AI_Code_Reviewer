"""极简 .env 解析器：只读取字面量 KEY=VALUE，不展开变量引用（与 PICO 行为一致）。"""

from __future__ import annotations

from pathlib import Path


def parse_env_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.lstrip("export ").strip() if line.startswith("export ") else line
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # 行内注释（仅未加引号的值）
        if " #" in value and not value.startswith(("'", '"')):
            value = value.split(" #", 1)[0].rstrip()
        if key:
            result[key] = value
    return result


def load_dotenv(path: str | Path) -> dict[str, str]:
    """加载 .env 文件并覆盖当前进程同名环境变量，返回本次加载的键值。"""
    import os

    p = Path(path)
    if not p.is_file():
        return {}
    loaded = parse_env_text(p.read_text(encoding="utf-8"))
    for key, value in loaded.items():
        os.environ[key] = value
    return loaded
