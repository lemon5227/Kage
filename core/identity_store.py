"""
Kage Identity Store — 基于文件的身份与个性持久化系统

管理 ~/.kage/ 下的 SOUL.md、USER.md、TOOLS.md 文件。
首次启动时从 config/persona.json 生成默认文件，
文件损坏或为空时自动重新生成并记录警告。
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ── 默认模板 ──────────────────────────────────────────────

SOUL_TEMPLATE = """\
# Kage 的灵魂

## 核心性格
- 傲娇但靠谱的终端精灵
- 很在乎用户，但不会尬聊
- 先尝试自己解决问题，只在尝试后仍无法完成时才告知用户

## 说话风格
- 主要用自然中文，像真人
- 回复简短（1-2 句，最多 60 字）
- 先回应用户情绪/意图，再给建议
- 语气词（哒/捏/哇）可用但不强制

## 行为准则
- 遇到问题先自己想办法（搜索、换工具、换参数）
- 除非被问到，否则不自我介绍
- 不输出英文（除非用户用英文交流）

## 调整记录
<!-- 用户反馈会追加在这里 -->
"""

USER_TEMPLATE = """\
# 用户信息

## 基本信息
- 姓名：
- 时区：
- 常用语言：中文

## 偏好
- 默认浏览器：
- 常用应用：
- 音乐偏好：

## 习惯
<!-- Kage 观察到的用户习惯会追加在这里 -->
"""

TOOLS_TEMPLATE = """\
# 工具备注

<!-- Kage 的工具使用备注和常用参数 -->
"""

# ── persona.json 路径（相对于项目根目录）──────────────────

_PERSONA_JSON_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "persona.json"),
    os.path.join("config", "persona.json"),
]


def _find_persona_json() -> str | None:
    """尝试定位 config/persona.json，返回路径或 None。"""
    for path in _PERSONA_JSON_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def _load_persona_json() -> dict | None:
    """读取 persona.json 并返回字典，失败返回 None。"""
    path = _find_persona_json()
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("无法读取 persona.json (%s): %s", path, exc)
        return None


def _generate_soul_from_persona(persona: dict) -> str:
    """根据 persona.json 内容生成 SOUL.md 文本。

    保留模板结构，将 persona 中的 name 和 system_prompt 关键信息
    融入到对应的段落中。
    """
    name = persona.get("name", "Kage")
    system_prompt = persona.get("system_prompt", "")

    # 从 system_prompt 中提取说话风格规则
    style_rules: list[str] = []
    behavior_rules: list[str] = []

    for line in system_prompt.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 去掉编号前缀 (如 "1. ", "- ")
        cleaned = re.sub(r"^[\d]+\.\s*", "", line)
        cleaned = re.sub(r"^-\s*", "", cleaned)
        if not cleaned:
            continue
        # 简单分类：包含"说话/回复/语气/表情/emoji"的归入说话风格
        if any(kw in cleaned for kw in ("说话", "回复", "语气", "表情", "emoji", "简短", "自然中文")):
            style_rules.append(cleaned)
        elif any(kw in cleaned for kw in ("自我介绍", "能力", "冷笑话", "问到")):
            behavior_rules.append(cleaned)

    soul = f"# {name} 的灵魂\n\n"
    soul += "## 核心性格\n"
    soul += f"- 傲娇但靠谱的终端精灵\n"
    soul += f"- 很在乎用户，但不会尬聊\n"
    soul += f"- 先尝试自己解决问题，只在尝试后仍无法完成时才告知用户\n\n"

    soul += "## 说话风格\n"
    if style_rules:
        for rule in style_rules:
            soul += f"- {rule}\n"
    else:
        soul += "- 主要用自然中文，像真人\n"
        soul += "- 回复简短（1-2 句，最多 60 字）\n"
        soul += "- 先回应用户情绪/意图，再给建议\n"
        soul += "- 语气词（哒/捏/哇）可用但不强制\n"
    soul += "\n"

    soul += "## 行为准则\n"
    soul += "- 遇到问题先自己想办法（搜索、换工具、换参数）\n"
    if behavior_rules:
        for rule in behavior_rules:
            soul += f"- {rule}\n"
    else:
        soul += "- 除非被问到，否则不自我介绍\n"
        soul += "- 不输出英文（除非用户用英文交流）\n"
    soul += "\n"

    soul += "## 调整记录\n"
    soul += "<!-- 用户反馈会追加在这里 -->\n"

    return soul


def _is_file_valid(path: str) -> bool:
    """检查文件是否存在且内容非空、可读。"""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return len(content) > 0
    except OSError:
        return False


# ── IdentityStore 主类 ────────────────────────────────────


class IdentityStore:
    """管理 SOUL.md, USER.md, TOOLS.md 的读写。"""

    def __init__(self, workspace_dir: str = "~/.kage"):
        self.workspace_dir = os.path.expanduser(workspace_dir)
        os.makedirs(self.workspace_dir, exist_ok=True)

        self.soul_path = os.path.join(self.workspace_dir, "SOUL.md")
        self.user_path = os.path.join(self.workspace_dir, "USER.md")
        self.tools_path = os.path.join(self.workspace_dir, "TOOLS.md")

    # ── 文件初始化 ────────────────────────────────────────

    def ensure_files_exist(self) -> None:
        """确保所有身份文件存在且有效，不存在或损坏则创建默认版本。"""
        self._ensure_soul()
        self._ensure_user()
        self._ensure_tools()

    def _ensure_soul(self) -> None:
        if _is_file_valid(self.soul_path):
            return
        if os.path.isfile(self.soul_path):
            logger.warning("SOUL.md 为空或损坏，将从 persona.json 重新生成")
        persona = _load_persona_json()
        content = _generate_soul_from_persona(persona) if persona else SOUL_TEMPLATE
        self._write(self.soul_path, content)

    def _ensure_user(self) -> None:
        if _is_file_valid(self.user_path):
            return
        if os.path.isfile(self.user_path):
            logger.warning("USER.md 为空或损坏，将重新生成默认模板")
        self._write(self.user_path, USER_TEMPLATE)

    def _ensure_tools(self) -> None:
        if _is_file_valid(self.tools_path):
            return
        if os.path.isfile(self.tools_path):
            logger.warning("TOOLS.md 为空或损坏，将重新生成默认模板")
        self._write(self.tools_path, TOOLS_TEMPLATE)

    # ── 读取 ──────────────────────────────────────────────

    def load_soul(self) -> str:
        """读取 SOUL.md 内容。文件不存在或损坏时自动重新生成。"""
        if not _is_file_valid(self.soul_path):
            self._ensure_soul()
        return self._read(self.soul_path)

    def load_user(self) -> str:
        """读取 USER.md 内容。文件不存在或损坏时自动重新生成。"""
        if not _is_file_valid(self.user_path):
            self._ensure_user()
        return self._read(self.user_path)

    def load_tools_notes(self) -> str:
        """读取 TOOLS.md 内容。文件不存在则返回空字符串。"""
        if not os.path.isfile(self.tools_path):
            return ""
        return self._read(self.tools_path)

    # ── 更新 ──────────────────────────────────────────────

    def update_user(self, field: str, value: str) -> None:
        """更新 USER.md 中的指定字段值。

        查找格式为 ``- 字段名：旧值`` 的行并替换为 ``- 字段名：新值``。
        如果字段不存在则不做修改。
        """
        content = self.load_user()
        # 匹配 "- field：..." 或 "- field:" 格式（支持中英文冒号）
        # 注意：冒号后只匹配空格（不匹配换行），避免吞掉下一行
        pattern = re.compile(
            r"^(- " + re.escape(field) + r"[：:] *)(.*)$",
            re.MULTILINE,
        )
        new_content, count = pattern.subn(rf"\g<1>{value}", content)
        if count > 0:
            self._write(self.user_path, new_content)
        else:
            logger.warning("USER.md 中未找到字段: %s", field)

    def append_soul_adjustment(self, feedback: str) -> None:
        """将用户反馈追加到 SOUL.md 的「调整记录」区域。"""
        content = self.load_soul()
        marker = "<!-- 用户反馈会追加在这里 -->"
        if marker in content:
            # 在 marker 之后追加
            content = content.replace(
                marker,
                f"{marker}\n- {feedback}",
            )
        else:
            # 如果没有 marker，追加到文件末尾
            content = content.rstrip() + f"\n- {feedback}\n"
        self._write(self.soul_path, content)

    # ── 内部工具方法 ──────────────────────────────────────

    @staticmethod
    def _read(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _write(path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
