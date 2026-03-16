"""
Kage Session Manager — 会话持久化与恢复

管理 ~/.kage/sessions/ 下的会话文件。
每轮对话追加写入 current.jsonl，重启后从文件恢复。
空闲超过 30 分钟自动归档为 YYYY-MM-DD-HH-MM.jsonl。
损坏文件重命名为 .bak 并创建新文件。
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────

MAX_HISTORY = 20
IDLE_TIMEOUT_SEC = 1800  # 30 分钟
CURRENT_FILENAME = "current.jsonl"


class SessionManager:
    """会话管理：持久化到文件，支持恢复。"""

    def __init__(self, workspace_dir: str = "~/.kage"):
        self.workspace_dir = os.path.expanduser(workspace_dir)
        self.sessions_dir = os.path.join(self.workspace_dir, "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)

        self.current_file = os.path.join(self.sessions_dir, CURRENT_FILENAME)
        self._history: list[dict] = []

    # ── 对话轮次 ──────────────────────────────────────────

    def add_turn(self, role: str, content: str) -> None:
        """添加对话轮次到内存和文件。

        Args:
            role: "user" 或 "assistant"
            content: 对话内容（非空字符串）
        """
        role = str(role or "").strip()
        if role not in ("user", "assistant"):
            return
        content = str(content or "").strip()
        if not content:
            return

        turn = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._history.append(turn)
        self._append_to_file(turn)

    def get_history(self) -> list[dict[str, str]]:
        """获取当前会话历史（最近 MAX_HISTORY 轮）。

        返回仅包含 role 和 content 的字典列表，
        与 LLM 消息格式兼容。
        """
        recent = self._history[-MAX_HISTORY:]
        return [{"role": t["role"], "content": t["content"]} for t in recent]

    # ── 持久化 ────────────────────────────────────────────

    def load_from_file(self) -> None:
        """从 current.jsonl 恢复会话。

        逐行解析 JSON，跳过损坏行。
        如果整个文件无法读取，重命名为 .bak 并创建新文件。
        """
        if not os.path.isfile(self.current_file):
            return

        try:
            with open(self.current_file, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
        except OSError as exc:
            logger.warning("无法读取 %s: %s", self.current_file, exc)
            self._handle_corrupted_file()
            return

        loaded: list[dict] = []
        corrupted_lines = 0

        for i, line in enumerate(raw_lines):
            line = line.strip()
            if not line:
                continue
            try:
                turn = json.loads(line)
                if isinstance(turn, dict) and "role" in turn and "content" in turn:
                    loaded.append(turn)
                else:
                    corrupted_lines += 1
                    logger.warning("current.jsonl 第 %d 行缺少必要字段，已跳过", i + 1)
            except json.JSONDecodeError:
                corrupted_lines += 1
                logger.warning("current.jsonl 第 %d 行 JSON 解析失败，已跳过", i + 1)

        if corrupted_lines > 0 and len(loaded) == 0:
            # 整个文件都损坏了
            logger.warning("current.jsonl 完全损坏，重命名为 .bak")
            self._handle_corrupted_file()
            return

        self._history = loaded

    def _append_to_file(self, turn: dict) -> None:
        """将一轮对话追加写入 current.jsonl。"""
        try:
            with open(self.current_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("无法写入 %s: %s", self.current_file, exc)

    def _handle_corrupted_file(self) -> None:
        """处理损坏文件：重命名为 .bak 并创建新空文件。"""
        bak_path = self.current_file + ".bak"
        try:
            # 如果已有 .bak 文件，覆盖它
            if os.path.isfile(self.current_file):
                os.replace(self.current_file, bak_path)
                logger.info("已将损坏文件重命名为 %s", bak_path)
        except OSError as exc:
            logger.warning("无法重命名损坏文件: %s", exc)

        # 创建新的空文件
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                pass  # 空文件
        except OSError as exc:
            logger.warning("无法创建新的 current.jsonl: %s", exc)

        self._history = []

    # ── 归档 ──────────────────────────────────────────────

    def archive_if_idle(self) -> bool:
        """如果空闲超过 30 分钟，归档当前会话并创建新会话。

        Returns:
            True 如果执行了归档，False 如果未归档。
        """
        last_time = self.get_last_user_time()
        if last_time is None:
            return False

        elapsed = time.time() - last_time
        if elapsed < IDLE_TIMEOUT_SEC:
            return False

        # 归档：重命名 current.jsonl 为 YYYY-MM-DD-HH-MM.jsonl
        archive_name = datetime.now().strftime("%Y-%m-%d-%H-%M") + ".jsonl"
        archive_path = os.path.join(self.sessions_dir, archive_name)

        try:
            if os.path.isfile(self.current_file):
                os.replace(self.current_file, archive_path)
                logger.info("会话已归档为 %s", archive_name)
        except OSError as exc:
            logger.warning("归档失败: %s", exc)
            return False

        # 创建新的空 current.jsonl
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                pass
        except OSError as exc:
            logger.warning("无法创建新的 current.jsonl: %s", exc)

        self._history = []
        return True

    # ── 时间查询 ──────────────────────────────────────────

    def get_last_user_time(self) -> float | None:
        """获取最近一次用户输入的时间戳（Unix epoch 秒）。

        Returns:
            时间戳浮点数，如果没有用户输入则返回 None。
        """
        for turn in reversed(self._history):
            if turn.get("role") == "user":
                ts = turn.get("timestamp")
                if ts is not None:
                    try:
                        dt = datetime.fromisoformat(ts)
                        return dt.timestamp()
                    except (ValueError, TypeError):
                        pass
        return None
