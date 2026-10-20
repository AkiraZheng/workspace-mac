"""poll 通知:写 NOTIFY.md + 供外部脚本判断的返回信息。"""

from __future__ import annotations

import json
from pathlib import Path

from harness.series.store import SeriesStore, now_iso


def write_notify(store: SeriesStore, round_no: int, new_items: list[dict],
                 mode: str) -> Path:
    out = store.dir / "NOTIFY.md"
    pending = [it for it in new_items if it["status"] == "pending"]
    lines = [f"# 新检视意见 — round {round_no}", "",
             f"- 拉取模式: {mode}  时间: {now_iso()}",
             f"- 新增意见: {len(new_items)} 条(待分析 {len(pending)} 条)", ""]
    if new_items:
        lines.append("| id | 来自 | 分类 | 针对 patch | 主题 |")
        lines.append("|---|---|---|---|---|")
        for it in new_items:
            lines.append(f"| {it['id']} | {it['source']['from_name']} | "
                         f"{it['source']['sender_class']} | {it['target_patch']['seq']} | "
                         f"{(it['source']['subject'] or '')[:60]} |")
        lines.append("")
    if pending:
        lines.append("**下一步**: 运行 `/autofix-upstream triage` 完成分析,"
                     "再按需 `/autofix-upstream fix`。")
    else:
        lines.append("(无待分析意见 — 均为作者自述或已闭环)")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
