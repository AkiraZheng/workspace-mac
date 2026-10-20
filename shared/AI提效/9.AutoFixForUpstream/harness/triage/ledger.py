"""检视意见台账:stub 生成、LLM 产物合并(校验后)、人读渲染。

triage.json 永远只有 harness 这一个写者;LLM 的分析结果写到
reviews/round-N/item-<id>.json(triage_item_llm schema 子集),
由 merge_round 校验后并入。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from harness.common.json_utils import SCHEMA_DIR
from harness.lore import thread as thread_mod
from harness.lore.thread import MailMsg
from harness.series.store import SeriesStore, now_iso
from harness.triage.classify import SenderClass, classify, load_rules


def _default_rules_path() -> Path:
    """PROJECT_ROOT/config/reviewers.yaml(harness/../.. 即项目根)。"""
    return Path(__file__).resolve().parent.parent.parent / "config" / "reviewers.yaml"

LLM_MERGE_FIELDS = (
    "verdict", "fix_type", "summary_zh", "quotes", "analysis_zh",
    "fix_approach_zh", "ai_scrutiny", "message_change_needed",
    "message_change_text", "changelog_en",
)

STATUS_BY_VERDICT = {
    "invalid": "invalid",
    "record_only": "record_only",
    "valid": "analyzed",
    "partial": "analyzed",
    "question": "analyzed",
}


def make_stubs(store: SeriesStore, msgs: list[MailMsg], round_no: int,
               patch_index: dict[str, int], msg_index: dict[str, MailMsg]) -> list[str]:
    """为新意见生成台账 item,返回新 item id 列表。"""
    rules = load_rules(_default_rules_path())
    authors = set(store.cfg.get("series_authors") or [])
    store.reviews_dir(round_no).mkdir(parents=True, exist_ok=True)
    items = store.items()
    existing_ids = {it["id"] for it in items}
    counter = len([it for it in items if it.get("round") == round_no]) + 1
    new_ids: list[str] = []
    for msg in msgs:
        verdict = classify(msg, rules, authors)
        item_id = f"r{round_no}-{counter:03d}"
        while item_id in existing_ids:
            counter += 1
            item_id = f"r{round_no}-{counter:03d}"
        counter += 1
        seq = thread_mod.associate(msg, patch_index, msg_index)
        status = "record_only" if verdict.cls is SenderClass.AUTHOR else "pending"
        items.append({
            "id": item_id,
            "round": round_no,
            "status": status,
            "verdict": None,
            "fix_type": None,
            "source": {
                "message_id": msg.msgid,
                "in_reply_to": msg.in_reply_to,
                "from_name": msg.from_name,
                "from_email": msg.from_email,
                "date": msg.date,
                "subject": msg.subject_clean,
                "eml_path": str(msg.path.relative_to(store.dir)),
                "sender_class": verdict.cls.value,
                "sender_rule": verdict.rule,
            },
            "target_patch": {"seq": seq, "subject": thread_mod.subject_of_seq(
                list(msg_index.values()), seq) if seq and seq > 0 else None},
            "summary_zh": None,
            "quotes": None,
            "analysis_zh": None,
            "fix_approach_zh": None,
            "ai_scrutiny": {"suspected_llm": False, "confidence": None, "note": None},
            "fix_commit": None,
            "message_change_needed": False,
            "message_change_text": None,
            "changelog_en": None,
            "decided_by": "human" if status == "record_only" else None,
            "decided_at": now_iso() if status == "record_only" else None,
        })
        new_ids.append(item_id)
    if new_ids:
        store.save_ledger(items)
    return new_ids


def merge_round(store: SeriesStore, round_no: int) -> dict:
    """校验并合并 reviews/round-N/item-*.json 到台账。

    返回 {merged: [...], rejected: [{file, errors}], missing: [...]}。
    """
    rdir = store.reviews_dir(round_no)
    items = store.items()
    by_id = {it["id"]: it for it in items}
    merged, rejected, missing = [], [], []
    files = sorted(rdir.glob("item-*.json")) if rdir.is_dir() else []
    llm_validator = jsonschema.Draft202012Validator(
        json.loads((SCHEMA_DIR / "triage.schema.json").read_text(encoding="utf-8"))["$defs"]["triage_item_llm"])
    covered = set()
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            rejected.append({"file": f.name, "errors": [f"JSON 解析失败: {e}"]})
            continue
        llm_errors = [e.message for e in sorted(llm_validator.iter_errors(data), key=lambda e: e.json_path)]
        if llm_errors:
            rejected.append({"file": f.name, "errors": llm_errors})
            continue
        item = by_id.get(data["id"])
        if item is None:
            rejected.append({"file": f.name, "errors": [f"台账中无此 item id: {data['id']}"]})
            continue
        for k in LLM_MERGE_FIELDS:
            if k in data:
                item[k] = data[k]
        item["status"] = STATUS_BY_VERDICT.get(data["verdict"], "analyzed")
        item["decided_by"] = "llm"
        item["decided_at"] = now_iso()
        covered.add(data["id"])
        merged.append(data["id"])
    # 该轮 pending 但没有 LLM 产物的 item
    for it in items:
        if it.get("round") == round_no and it["id"] not in covered and it["status"] == "pending":
            missing.append(it["id"])
    if merged:
        store.save_ledger(items)
    return {"merged": merged, "rejected": rejected, "missing": missing}


CLASS_LABEL = {
    "human": "人为", "ai_reviewer": "AI(sashiko 类)", "bot": "测试机器人", "author": "作者",
}


def render_md(store: SeriesStore) -> Path:
    """渲染台账 triage.md(可再生,不作为数据真源)。"""
    st = store.status_dict()
    items = store.items()
    lines = [f"# 检视意见台账 — {st['series_id']}", ""]
    lines.append(f"- phase: **{st['phase']}**  分支: `{st['branch']}`  base: `{st['base']}` "
                 f"patch 数: {st['patches']}  fix 数: {st['fixes']}")
    lines.append(f"- 轮次: {st['rounds']}  已见消息: {st['messages_seen']}  "
                 f"最近 poll: {st['last_poll'] or '从未'} ({st['last_poll_status'] or '-'})")
    lines.append(f"- 意见总数: {st['items_total']}(待分析 {st['pending']},"
                 f"待修复 {st['fixable']},未闭环 {st['unresolved']})")
    lines.append("")
    lines.append("## 待办")
    todo = [it for it in items if it["status"] in ("pending", "analyzed")]
    if not todo:
        lines.append("(无 — 全部意见已闭环)")
    for it in todo:
        lines.append(f"- [ ] **{it['id']}** [{it['status']}] "
                     f"{CLASS_LABEL.get(it['source']['sender_class'], '?')} · patch {it['target_patch']['seq']} · "
                     f"{it['source']['from_name']}: {(it['summary_zh'] or it['source']['subject'])[:60]}")
    lines.append("")
    lines.append("## 逐条详情")
    for it in items:
        src = it["source"]
        lines.append("")
        lines.append(f"### {it['id']} — {src['from_name']} <{src['from_email']}>")
        lines.append(f"- 分类: {CLASS_LABEL.get(src['sender_class'], src['sender_class'])}"
                     f"({src['sender_rule']})  状态: **{it['status']}**  判定: {it.get('verdict') or '-'}"
                     f"  修复类型: {it.get('fix_type') or '-'}")
        lines.append(f"- 邮件: `{src['message_id']}`  ({src['date']})  针对patch: {it['target_patch']['seq']}")
        lines.append(f"- 原文: `{src['eml_path']}`")
        if it.get("summary_zh"):
            lines.append(f"- 摘要: {it['summary_zh']}")
        if it.get("quotes"):
            lines.append("- 引用:")
            for q in it["quotes"][:5]:
                lines.append(f"  > {q[:150]}")
        if it.get("analysis_zh"):
            lines.append(f"- 分析: {it['analysis_zh']}")
        if it.get("fix_approach_zh"):
            lines.append(f"- 方案: {it['fix_approach_zh']}")
        if it.get("ai_scrutiny", {}).get("suspected_llm"):
            lines.append(f"- AI甄别: 疑似LLM({it['ai_scrutiny'].get('confidence')}) {it['ai_scrutiny'].get('note') or ''}")
        if it.get("fix_commit"):
            lines.append(f"- fix commit: `{it['fix_commit']}`")
        if it.get("changelog_en"):
            lines.append(f"- changelog(EN): {it['changelog_en']}")
    out = store.dir / "triage.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
