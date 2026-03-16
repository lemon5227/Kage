from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingVideoFollowup:
    source: str = "youtube"
    sort: str = "latest"
    last_url: str = ""
    last_title: str = ""
    last_channel: str = ""


@dataclass(frozen=True)
class PendingConfirmInferredCommand:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PendingConfirmTool:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PendingChatFollowup:
    topic: str = ""
    asked: str = ""


def make_pending_video_followup(
    *,
    source: str = "youtube",
    sort: str = "latest",
    last_url: str = "",
    last_title: str = "",
    last_channel: str = "",
) -> PendingVideoFollowup:
    return PendingVideoFollowup(
        source=str(source or "youtube"),
        sort=str(sort or "latest"),
        last_url=str(last_url or ""),
        last_title=str(last_title or ""),
        last_channel=str(last_channel or ""),
    )


def make_pending_confirm_inferred_command(name: str, arguments: Any) -> PendingConfirmInferredCommand:
    return PendingConfirmInferredCommand(
        name=str(name or ""),
        arguments=dict(arguments) if isinstance(arguments, dict) else {},
    )


def make_pending_confirm_tool(name: str, arguments: Any) -> PendingConfirmTool:
    return PendingConfirmTool(
        name=str(name or ""),
        arguments=dict(arguments) if isinstance(arguments, dict) else {},
    )


def make_pending_chat_followup(*, topic: str = "", asked: str = "") -> PendingChatFollowup:
    return PendingChatFollowup(
        topic=str(topic or ""),
        asked=str(asked or ""),
    )


def pending_requires_thinking(pending: Any) -> bool:
    return isinstance(
        pending,
        (
            PendingVideoFollowup,
            PendingConfirmInferredCommand,
            PendingConfirmTool,
        ),
    )


def pending_kind(pending: Any) -> str:
    if isinstance(pending, PendingVideoFollowup):
        return "video_followup"
    if isinstance(pending, PendingConfirmInferredCommand):
        return "confirm_inferred_command"
    if isinstance(pending, PendingConfirmTool):
        return "confirm_tool"
    if isinstance(pending, PendingChatFollowup):
        return "chat_followup"
    return "unknown"
