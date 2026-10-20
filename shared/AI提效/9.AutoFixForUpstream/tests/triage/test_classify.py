"""发送者三分类。"""

from pathlib import Path

from harness.lore.thread import MailMsg
from harness.triage.classify import SenderClass, classify, load_rules

RULES = load_rules(Path(__file__).resolve().parent.parent.parent / "config" / "reviewers.yaml")


def msg(email, name=""):
    return MailMsg(path=Path("/dev/null"), msgid=f"<{email}>", in_reply_to=None,
                   from_name=name, from_email=email)


AUTHORS = {"zhengtian10@huawei.com"}


def test_author_first():
    v = classify(msg("zhengtian10@huawei.com", "Tian Zheng"), RULES, AUTHORS)
    assert v.cls is SenderClass.AUTHOR


def test_bot_beats_others():
    v = classify(msg("oliver.sang@intel.com", "kernel test robot"), RULES, AUTHORS)
    assert v.cls is SenderClass.BOT
    v = classify(msg("x@syzkaller.appspotmail.com", "syzbot"), RULES, AUTHORS)
    assert v.cls is SenderClass.BOT


def test_ai_reviewer():
    v = classify(msg("sashiko-bot@kernel.org", "sashiko"), RULES, AUTHORS)
    assert v.cls is SenderClass.AI_REVIEWER


def test_human_priority_and_default():
    v = classify(msg("maz@kernel.org", "Marc Zyngier"), RULES, AUTHORS)
    assert v.cls is SenderClass.HUMAN and "humans_priority" in v.rule
    v = classify(msg("someone@newdomain.com", "New Guy"), RULES, AUTHORS)
    assert v.cls is SenderClass.HUMAN and v.rule == "default"
