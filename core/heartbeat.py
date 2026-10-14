"""
Heartbeat — 主动行为系统

周期性后台检查：
- 从 HEARTBEAT.md 读取检查项
- 按间隔执行检查（钳位到 [5, 120] 分钟）
- 用户活跃时暂存通知，空闲后发送
- 检查失败记录到 heartbeat_error.log，下周期重试
- 生成的通知交给 on_notifications 回调送达用户（WebSocket/语音）
"""

import asyncio
import datetime
import logging
import os
import time
from collections import OrderedDict
from typing import Awaitable, Callable, Optional

from core.proactive import ProactiveFeedbackStore, make_notification

logger = logging.getLogger(__name__)

MIN_INTERVAL_MIN = 5
MAX_INTERVAL_MIN = 120
DEFAULT_INTERVAL_MIN = 30
ACTIVE_THRESHOLD_SEC = 120  # 2 minutes
DELIVERED_MEMORY = 200  # delivered notifications remembered for feedback lookup


def clamp_interval(minutes: int | float) -> int:
    """Clamp heartbeat interval to [5, 120] minutes."""
    return max(MIN_INTERVAL_MIN, min(MAX_INTERVAL_MIN, int(minutes)))


class Heartbeat:
    """周期性后台检查"""

    def __init__(self, tool_executor, session_manager,
                 workspace_dir: str = "~/.kage",
                 interval_minutes: int = DEFAULT_INTERVAL_MIN,
                 on_notifications: Optional[Callable[[list[dict]], Awaitable[None]]] = None):
        self.tool_executor = tool_executor
        self.on_notifications = on_notifications
        self.session = session_manager

        workspace = os.path.expanduser(workspace_dir)
        os.makedirs(workspace, exist_ok=True)

        self.heartbeat_file = os.path.join(workspace, "HEARTBEAT.md")
        self.error_log_file = os.path.join(workspace, "heartbeat_error.log")
        self.feedback = ProactiveFeedbackStore(os.path.join(workspace, "proactive_feedback.jsonl"))
        self._delivered: "OrderedDict[str, dict]" = OrderedDict()

        self.interval_sec = clamp_interval(interval_minutes) * 60
        self._notification_queue: list[dict] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the heartbeat loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat started (interval=%ds)", self.interval_sec)

    async def stop(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_sec)
                await self._run_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Heartbeat loop error: %s", exc)

    async def _run_once(self) -> list[dict]:
        """Run one check cycle and hand any due notifications to the delivery callback."""
        notifications = await self.tick()
        await self._deliver(notifications)
        return notifications

    async def _deliver(self, notifications: list[dict]) -> None:
        if not notifications or self.on_notifications is None:
            return
        for n in notifications:
            if n.get("id"):
                self._delivered[str(n["id"])] = n
        while len(self._delivered) > DELIVERED_MEMORY:
            self._delivered.popitem(last=False)
        try:
            await self.on_notifications(notifications)
        except Exception as exc:
            self._log_error("deliver", exc)

    def record_feedback(self, notification_id: str, action: str) -> Optional[dict]:
        """Record the user's reaction to a delivered notification.

        Returns the notification it refers to, or None when the id is unknown
        (e.g. delivered before a restart); unknown ids are not recorded because
        their source — needed for mute/snooze — is not known.
        """
        notification = self._delivered.get(str(notification_id or ""))
        if notification is None:
            return None
        self.feedback.record(notification["id"], notification.get("source", ""), action)
        return notification

    async def tick(self) -> list[dict]:
        """Execute one heartbeat check cycle.

        Returns list of notification dicts to send.
        """
        check_items = self.load_check_items()
        notifications: list[dict] = []

        for item in check_items:
            if not item.get("enabled", False):
                continue
            try:
                # For now, generate a simple notification per enabled check
                name = item.get("name", "unknown")
                notification = make_notification(
                    f"heartbeat:{name}", item.get("description", ""), type_=name,
                    now=datetime.datetime.now(),
                )
                notifications.append(notification)
            except Exception as exc:
                self._log_error(item.get("name", "unknown"), exc)

        # Queue or return based on user activity
        if self.is_user_active():
            self._notification_queue.extend(notifications)
            logger.debug("User active, queued %d notifications", len(notifications))
            return []
        else:
            # Flush queue + new notifications
            all_notifications = self._notification_queue + notifications
            self._notification_queue.clear()
            return all_notifications

    def is_user_active(self) -> bool:
        """Check if user had input within the last 2 minutes."""
        last_time = self.session.get_last_user_time()
        if last_time is None:
            return False
        return (time.time() - last_time) < ACTIVE_THRESHOLD_SEC

    def load_check_items(self) -> list[dict]:
        """Load check items from HEARTBEAT.md."""
        if not os.path.exists(self.heartbeat_file):
            return []

        try:
            with open(self.heartbeat_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            logger.error("Failed to read HEARTBEAT.md: %s", exc)
            return []

        return self._parse_heartbeat_md(content)

    def get_queued_notifications(self) -> list[dict]:
        """Return and clear the notification queue."""
        queued = list(self._notification_queue)
        self._notification_queue.clear()
        return queued

    def _parse_heartbeat_md(self, content: str) -> list[dict]:
        """Parse HEARTBEAT.md into check item dicts."""
        items = []
        current: dict | None = None

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("## "):
                if current:
                    items.append(current)
                current = {"name": line[3:].strip(), "enabled": False, "description": ""}
            elif current and line.startswith("- enabled:"):
                val = line.split(":", 1)[1].strip().lower()
                current["enabled"] = val == "true"
            elif current and line.startswith("- 描述："):
                current["description"] = line.split("：", 1)[1].strip()

        if current:
            items.append(current)

        return items

    def _log_error(self, check_name: str, exc: Exception) -> None:
        """Log heartbeat check error to error log file."""
        ts = datetime.datetime.now().isoformat()
        line = f"[{ts}] {check_name}: {type(exc).__name__}: {exc}\n"
        try:
            with open(self.error_log_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as write_exc:
            logger.error("Failed to write heartbeat error log: %s", write_exc)
