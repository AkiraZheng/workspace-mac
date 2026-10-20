"""发送者三分类(配置驱动):bot / ai_reviewer / human / author。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from harness.lore.thread import MailMsg


class SenderClass(str, Enum):
    HUMAN = "human"
    AI_REVIEWER = "ai_reviewer"
    BOT = "bot"
    AUTHOR = "author"


@dataclass
class SenderVerdict:
    cls: SenderClass
    rule: str  # 命中的规则说明(default / 规则内容)


def load_rules(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _match(msg: MailMsg, rule: dict) -> bool:
    if "email_re" in rule and msg.from_email:
        if re.fullmatch(rule["email_re"], msg.from_email, re.IGNORECASE):
            return True
    if "name_re" in rule and msg.from_name:
        if re.search(rule["name_re"], msg.from_name, re.IGNORECASE):
            return True
    return False


def classify(msg: MailMsg, rules: dict, series_authors: set[str]) -> SenderVerdict:
    """匹配顺序:系列作者 -> bots -> ai_reviewers -> humans_priority -> default。"""
    if msg.from_email.lower() in {a.lower() for a in series_authors}:
        return SenderVerdict(SenderClass.AUTHOR, "series_authors")
    for group, cls in (("bots", SenderClass.BOT), ("ai_reviewers", SenderClass.AI_REVIEWER)):
        for rule in rules.get(group) or []:
            if _match(msg, rule):
                return SenderVerdict(cls, f"{group}:{rule.get('email_re') or rule.get('name_re')}")
    for rule in rules.get("humans_priority") or []:
        if _match(msg, rule):
            return SenderVerdict(SenderClass.HUMAN, f"humans_priority:{rule.get('email_re') or rule.get('name_re')}")
    return SenderVerdict(SenderClass.HUMAN, "default")
