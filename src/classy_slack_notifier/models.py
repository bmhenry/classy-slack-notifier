"""Shared data structures used across all components."""

from dataclasses import dataclass
from enum import Enum


class FilterAction(Enum):
    SKIP = "skip"
    CLASSIFY = "classify"
    FORCE_NOTIFY = "force_notify"


@dataclass
class SlackMessage:
    channel: str  # channel name or ID
    channel_id: str  # raw channel ID
    sender: str  # display name or user ID
    sender_id: str  # raw user ID
    text: str  # message body
    thread_ts: str | None = None
    is_dm: bool = False
    is_mention: bool = False  # true if the bot user is @mentioned
    is_bot: bool = False  # true if the sender is a bot user


@dataclass
class Classification:
    urgency: int  # 1-5 scale
    reason: str  # brief explanation from the LLM


@dataclass
class FilterResult:
    action: FilterAction
    rule: str  # which rule triggered, e.g. "self", "bots", "keyword:production down"
