"""autofix-upstream CLI:供 skill(python 片段)与 bin/poll.sh 调用的确定性入口。

用法(在 PROJECT_ROOT 下执行):
    python3 -m harness.cli <command> [options]

命令一览:
    import         注册进行中的系列(import 模式)
    poll           拉取线程增量并生成台账 stub
    triage-merge   校验并合并 reviews/round-N/item-*.json
    triage-render  重新渲染 triage.md
    status         系列状态
    fix-record     登记新 fix commit(fix 流程)
    fix-associate  把已存在的 fix commit 关联到台账 item
    rebase-plan    生成 finalize rebase todo(打印,不执行)
    rebase-run     归档+备份+执行 rebase+sha 重映射
    export         format-patch 导出最终系列
    resync         master 前移后重算 base/shas
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from harness.common import gitops
from harness.cover.parse import parse_cover
from harness.cover.render import scaffold_next
from harness.finalize import autosquash, export as export_mod
from harness.lore import b4fetch, thread as thread_mod
from harness.lore.b4fetch import FetchError, fetch_thread, import_mbox_file, lore_url
from harness.notify import write_notify
from harness.series.importer import ImportError_, pair_msgids, resolve_sha, verify_topology
from harness.series.store import SeriesError, SeriesStore, find_series, now_iso
from harness.triage import ledger as ledger_mod


def _open_store(args) -> SeriesStore:
    repo = Path(args.repo).resolve()
    return SeriesStore(find_series(repo, getattr(args, "series_id", None)))


def _print_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _dirty_violations(store: SeriesStore) -> list[str]:
    """当前 git status 相对 import 时基线的新增条目(未跟踪的旧条目不算)。"""
    base = store.dir / "git-status-baseline.txt"
    if not base.is_file():
        return []
    baseline = set(l for l in base.read_text(encoding="utf-8").splitlines() if l.strip())
    cur = set(l for l in gitops.run_git(store.repo, "status", "--porcelain").stdout.splitlines() if l.strip())
    return sorted(cur - baseline)


def _write_dirty_baseline(store: SeriesStore) -> None:
    out = gitops.run_git(store.repo, "status", "--porcelain").stdout
    (store.dir / "git-status-baseline.txt").write_text(out, encoding="utf-8")


# ---------------------------------------------------------------- import

def cmd_import(args) -> int:
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    repo = Path(cfg["repo_path"])
    if gitops.current_branch(repo) != cfg["work_branch"]:
        print(f"错误: 请先在 {repo} checkout {cfg['work_branch']}"
              f"(当前 {gitops.current_branch(repo)})", file=sys.stderr)
        return 2
    fix_map: dict[str, int] = {}
    for pair in args.fix or []:
        sha, _, seq = pair.partition("=")
        fix_map[sha] = int(seq)

    base = cfg.get("base_commit")
    if not base:
        for ref in ("master", "main"):
            try:
                base = gitops.merge_base(repo, ref, "HEAD")
                break
            except gitops.GitError:
                continue
    if not base:
        raise SeriesError("series.yaml 缺 base_commit,且无法从 master/main 推断 merge-base")
    series, fixes = verify_topology(repo, base, list(fix_map))
    print(f"拓扑校验通过: {len(series)} 系列 commit + {len(fixes)} fix commit (base {base[:12]})")

    store = SeriesStore.create(repo, cfg["series_id"], cfg)
    if args.mbox_file:
        mode = import_mbox_file(args.mbox_file, store.round_mbox(0))
    else:
        mode = fetch_thread(cfg["prev_msgid"], store.round_mbox(0))
    msgs = thread_mod.split_mbox(store.round_mbox(0), store.round_dir(0))
    patch_index = thread_mod.patch_index_of(msgs)
    msg_index = {m.msgid: m for m in msgs}
    series_commits = pair_msgids(repo, series, msgs)

    fix_full = {resolve_sha(repo, s): seq for s, seq in fix_map.items()}
    fix_commits = [{
        "sha": f,
        "subject": gitops.subject_of(repo, f),
        "target_seq": fix_full[f],
        "origin": "imported",
    } for f in fixes]
    store.init_state(base, series_commits, fix_commits,
                     root_msgid=cfg["prev_msgid"], import_mode=True)

    new_non_patch = [m for m in msgs if not m.is_patch]
    new_ids = ledger_mod.make_stubs(store, new_non_patch, 0, patch_index, msg_index)
    st = store.state
    st["thread"]["messages_seen"] = sorted({m.msgid for m in msgs})
    st["thread"]["rounds"].append({"round": 0, "at": now_iso(),
                                   "new_messages": len(msgs),
                                   "mbox": "mboxes/round-0000.mbox"})
    store.save_state(thread=st["thread"])

    cover_msg = next((m for m in msgs if m.is_cover), None)
    if cover_msg is None:
        raise ImportError_("线程中找不到 cover letter([PATCH vN 00/MM])")
    doc = parse_cover(cover_msg.path)
    draft = store.dir / "cover" / f"cover-v{cfg['new_version']}.draft.md"
    scaffold_next(doc, cfg["new_version"], cfg["prev_version"],
                  lore_url(cfg["prev_msgid"]), len(series_commits), draft)
    ledger_mod.render_md(store)
    _write_dirty_baseline(store)
    pending = len(store.pending_items())
    print(f"导入完成: round-0 快照 {len(msgs)} 封,新意见 {len(new_ids)} 条"
          f"(待分析 {pending});cover 草稿: {draft}")
    _print_json({"series_id": cfg["series_id"], "mode": mode, "messages": len(msgs),
                 "new_items": new_ids, "pending": pending,
                 "series_commits": len(series_commits), "fix_commits": len(fix_commits)})
    return 0


# ---------------------------------------------------------------- poll

def _watch_threads(cfg: dict) -> list[tuple[str, str]]:
    """series.yaml watch_threads -> [(tag, msgid)]。

    元素为字符串时 tag 取 watch<N>;为 {tag, msgid} 时用显式 tag。
    """
    out: list[tuple[str, str]] = []
    for i, w in enumerate(cfg.get("watch_threads") or [], start=1):
        if isinstance(w, str):
            out.append((f"watch{i}", w))
        else:
            out.append((str(w.get("tag") or f"watch{i}"), str(w["msgid"])))
    return out


def cmd_poll(args) -> int:
    store = _open_store(args)
    store.require_phase("monitoring")
    st = store.state
    round_no = len(st["thread"]["rounds"])
    threads: list[tuple[str, str | None]] = [("primary", store.cfg["prev_msgid"])]
    threads += _watch_threads(store.cfg)

    seen = set(st["thread"]["messages_seen"])
    new_ids: list[str] = []
    per_thread: dict[str, dict] = {}
    mode = "b4"
    fetch_failed: list[str] = []

    for tag, msgid in threads:
        mbox_path = store.round_mbox(round_no, None if tag == "primary" else tag)
        try:
            if args.mbox_file and tag == "primary":
                tmode = import_mbox_file(args.mbox_file, mbox_path)
            else:
                tmode = fetch_thread(msgid, mbox_path)
            if tag == "primary":
                mode = tmode
        except FetchError as e:
            if tag == "primary":
                store.save_state(poll={"last_run_at": now_iso(), "last_status": "b4_error"})
                print(f"错误: {e}", file=sys.stderr)
                return 2
            fetch_failed.append(tag)
            print(f"警告: watch 线程 {tag} 拉取失败,跳过: {e}", file=sys.stderr)
            continue
        msgs = thread_mod.split_mbox(mbox_path, store.round_dir(round_no, None if tag == "primary" else tag))
        new = thread_mod.diff_msgids(msgs, seen)
        seen |= {m.msgid for m in new}
        if not new:
            per_thread[tag] = {"new_messages": 0, "new_items": []}
            continue
        patch_index = thread_mod.patch_index_of(msgs)
        msg_index = {m.msgid: m for m in msgs}
        new_non_patch = [m for m in new if not m.is_patch]
        ids = ledger_mod.make_stubs(store, new_non_patch, round_no, patch_index,
                                    msg_index, thread_tag=tag)
        new_ids += ids
        per_thread[tag] = {"new_messages": len(new), "new_items": ids}

    new_total = sum(t["new_messages"] for t in per_thread.values())
    if not new_total and not fetch_failed:
        store.save_state(poll={"last_run_at": now_iso(), "last_status": "ok"})
        _print_json({"round": round_no - 1 if st["thread"]["rounds"] else 0,
                     "new_messages": 0, "new_items": [], "new_pending": [],
                     "mode": mode})
        return 0
    if new_total:
        items_by_id = {it["id"]: it for it in store.items()}
        new_items = [items_by_id[i] for i in new_ids]
        st["thread"]["messages_seen"] = sorted(seen)
        st["thread"]["rounds"].append({"round": round_no, "at": now_iso(),
                                       "new_messages": new_total,
                                       "mbox": f"mboxes/round-{round_no:04d}.mbox",
                                       "watch_mboxes": {t: f"mboxes/round-{round_no:04d}-{t}.mbox"
                                                        for t, _ in threads[1:]}})
        store.save_state(thread=st["thread"], poll={"last_run_at": now_iso(), "last_status": "ok"})
        ledger_mod.render_md(store)
        write_notify(store, round_no, new_items, mode)
        pending_ids = [it["id"] for it in new_items if it["status"] == "pending"]
        dirty = _dirty_violations(store)
        if dirty:
            store.save_state(poll={"last_run_at": now_iso(), "last_status": "dirty_tree"})
            _print_json({"round": round_no, "new_messages": new_total, "mode": mode,
                         "new_items": new_ids, "new_pending": pending_ids,
                         "per_thread": per_thread, "fetch_failed": fetch_failed,
                         "ALERT_dirty_tree": dirty[:10]})
            print("ALERT: 内核仓库出现基线之外的改动,请人工检查 git status", file=sys.stderr)
            return 4
        _print_json({"round": round_no, "new_messages": new_total, "mode": mode,
                     "new_items": new_ids, "new_pending": pending_ids,
                     "per_thread": per_thread, "fetch_failed": fetch_failed})
        return 0
    # 仅 watch 线程全部拉取失败:记 b4_error 但不产生新意见
    store.save_state(poll={"last_run_at": now_iso(), "last_status": "b4_error"})
    _print_json({"round": round_no - 1 if st["thread"]["rounds"] else 0,
                 "new_messages": 0, "new_items": [], "new_pending": [],
                 "mode": mode, "fetch_failed": fetch_failed})
    return 3


# ---------------------------------------------------------------- triage

def cmd_triage_merge(args) -> int:
    store = _open_store(args)
    report = ledger_mod.merge_round(store, args.round)
    ledger_mod.render_md(store)
    _print_json(report)
    if report["rejected"]:
        return 1
    return 0


def cmd_triage_render(args) -> int:
    store = _open_store(args)
    print(ledger_mod.render_md(store))
    return 0


# ---------------------------------------------------------------- status

def cmd_status(args) -> int:
    store = _open_store(args)
    st = store.status_dict()
    if args.json:
        _print_json(st)
        return 0
    print(f"系列: {st['series_id']}  phase: {st['phase']}")
    print(f"分支: {st['branch']}  base: {st['base']}  patch: {st['patches']}  fix: {st['fixes']}")
    print(f"轮次: {st['rounds']}  已见消息: {st['messages_seen']}  "
          f"最近 poll: {st['last_poll'] or '从未'} ({st['last_poll_status'] or '-'})")
    print(f"意见: 总 {st['items_total']}  待分析 {st['pending']}  待修复 {st['fixable']}  "
          f"未闭环 {st['unresolved']}")
    if st["items_by_status"]:
        for k, v in sorted(st["items_by_status"].items()):
            print(f"  {k}: {v}")
    if st["pending"]:
        print("下一步: /autofix-upstream triage")
    elif st["fixable"]:
        print("下一步: /autofix-upstream fix")
    elif st["unresolved"]:
        print("下一步: 处理未闭环意见(见 triage.md)")
    else:
        print("下一步: 意见已稳定,可 /autofix-upstream finalize")
    return 0


# ---------------------------------------------------------------- fix

def cmd_fix_record(args) -> int:
    store = _open_store(args)
    full = resolve_sha(store.repo, args.sha)
    store.record_fix(full, args.target_seq, args.origin)
    if args.item:
        store.update_item(args.item, fix_commit=full[:12], status="fixed")
    ledger_mod.render_md(store)
    _print_json({"recorded": full, "target_seq": args.target_seq,
                 "origin": args.origin, "item": args.item})
    return 0


def cmd_fix_associate(args) -> int:
    store = _open_store(args)
    full = resolve_sha(store.repo, args.sha)
    item = store.update_item(args.item, fix_commit=full[:12], status="fixed",
                             decided_by="human", decided_at=now_iso())
    st = store.state
    for fx in st["fix_commits"]:
        if fx["sha"] == full:
            fx["origin"] = args.item
    store.save_state(fix_commits=st["fix_commits"])
    ledger_mod.render_md(store)
    _print_json({"item": args.item, "fix_commit": full, "origin": item["id"]})
    return 0


# ---------------------------------------------------------------- finalize

def _rewords_from_args(args) -> dict[int, Path]:
    rewords: dict[int, Path] = {}
    for pair in args.msg_file or []:
        seq, _, path = pair.partition("=")
        rewords[int(seq)] = Path(path)
    return rewords


def cmd_rebase_plan(args) -> int:
    store = _open_store(args)
    st = store.state
    todo = autosquash.build_todo(st, store.repo, _rewords_from_args(args))
    autosquash.check_orphans(todo, store.repo, st["base"]["commit"])
    print(f"# fix -> patch 映射(base {st['base']['commit'][:12]}):")
    for fx in st["fix_commits"]:
        print(f"#   {fx['sha'][:12]} ({fx['subject'][:50]}) -> seq {fx['target_seq']}")
    print("\n".join(todo))
    return 0


def cmd_rebase_run(args) -> int:
    store = _open_store(args)
    store.require_phase("monitoring")
    st = store.state
    todo = autosquash.build_todo(st, store.repo, _rewords_from_args(args))
    ts = time.strftime("%Y%m%d-%H%M%S")
    archive_dir = store.dir / "final" / f"fixup-archive-{ts}"
    autosquash.archive_fixups(store.repo, [f["sha"] for f in st["fix_commits"]], archive_dir)
    backup = autosquash.create_backup_branch(
        store.repo, f"backup/{st['series_id']}-{ts}")
    store.save_state(phase="finalizing", final={
        "started_at": now_iso(), "rebase": {"done": False, "old_to_new": {}},
        "backup_branch": backup, "export_dir": None})
    try:
        autosquash.run_rebase(store.repo, st["base"]["commit"], todo,
                              store.dir / "final" / "rebase-todo")
    except autosquash.RebaseError:
        store.save_state(phase="monitoring", final={
            "started_at": None, "rebase": {"done": False, "old_to_new": {}},
            "backup_branch": backup, "export_dir": None})
        raise
    old_to_new = autosquash.remap_shas(store.repo, st["base"]["commit"], st)
    store.save_state(series_commits=st["series_commits"],
                     final={"started_at": now_iso(),
                            "rebase": {"done": True, "old_to_new": old_to_new},
                            "backup_branch": backup, "export_dir": None})
    print(f"rebase 完成: {len(st['fix_commits'])} 个 fix 已挤入 {len(st['series_commits'])} 个 patch;"
          f"备份分支 {backup},fix 归档 {archive_dir}")
    _print_json({"old_to_new": {k[:12]: v[:12] for k, v in old_to_new.items()},
                 "backup_branch": backup})
    return 0


def cmd_export(args) -> int:
    store = _open_store(args)
    st = store.state
    if not st["final"]["rebase"]["done"]:
        print("错误: 尚未执行 rebase-run,fix 还在 patch 之上", file=sys.stderr)
        return 2
    cover = Path(args.cover) if args.cover else \
        store.dir / "cover" / f"cover-v{store.cfg['new_version']}.final.md"
    if not cover.is_file():
        print(f"错误: cover 定稿不存在: {cover}(先完成 cover 定稿)", file=sys.stderr)
        return 2
    out_dir = store.dir / "final" / f"v{store.cfg['new_version']}"
    patches = export_mod.export_series(store.repo, st["base"]["commit"],
                                       store.cfg["new_version"], cover, out_dir)
    store.save_state(phase="done", final={**st["final"], "export_dir": str(out_dir)})
    print(f"导出 {len(patches)} 个文件到 {out_dir}(含 cover;checkpatch 请自行复核)")
    _print_json({"export_dir": str(out_dir), "files": [p.name for p in patches]})
    return 0


def cmd_send(args) -> int:
    """铁律占位:工作流绝不发送 patch,此命令永远拒绝。"""
    print("铁律: 本工作流只负责修改并产出下一版系列(final/v<N>/ 下的文件),"
          "绝不发送 patch。\n发送必须由用户在工作流之外人工完成"
          "(git send-email / b4 send 均不在此处执行)。", file=sys.stderr)
    return 2


def cmd_resync(args) -> int:
    store = _open_store(args)
    st = store.state
    base = gitops.merge_base(store.repo, "master", "HEAD")
    commits = gitops.rev_list(store.repo, base)
    fix_subjects = {f["subject"] for f in st["fix_commits"]}
    series = [c for c in commits if gitops.subject_of(store.repo, c) not in fix_subjects]
    fixes = [c for c in commits if gitops.subject_of(store.repo, c) in fix_subjects]
    if len(series) != len(st["series_commits"]):
        print(f"错误: resync 后系列 commit 数 {len(series)} != 记录 {len(st['series_commits'])},"
              "请人工检查", file=sys.stderr)
        return 2
    for sc, sha in zip(st["series_commits"], series):
        sc["sha"], sc["new_sha"] = sha, None
    for fx, sha in zip(st["fix_commits"], fixes):
        fx["sha"] = sha
    store.save_state(base={"commit": base, "subject": gitops.subject_of(store.repo, base)},
                     series_commits=st["series_commits"], fix_commits=st["fix_commits"])
    print(f"resync 完成: base -> {base[:12]},系列 {len(series)} + fix {len(fixes)}")
    return 0


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    # 铁律:send 在 argparse 之前直接拦截,任何参数形式一律拒绝
    if argv and argv[0] == "send":
        return cmd_send(None)
    p = argparse.ArgumentParser(prog="autofix-upstream", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--repo", default=".", help="内核仓库路径(默认当前目录)")
        sp.add_argument("--series-id", default=None, help="系列 id(单系列可省)")

    sp = sub.add_parser("import", help="注册进行中的系列")
    sp.add_argument("--config", required=True, help="series.yaml 模板路径")
    sp.add_argument("--fix", action="append", metavar="SHA=SEQ",
                    help="fix commit -> 目标 patch seq(可多次)")
    sp.add_argument("--mbox-file", default=None, help="离线线程 mbox(网络故障兜底)")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("poll", help="拉取线程增量")
    common(sp)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--mbox-file", default=None)
    sp.set_defaults(func=cmd_poll)

    sp = sub.add_parser("triage-merge", help="校验合并 LLM 分析产物")
    common(sp)
    sp.add_argument("--round", type=int, required=True)
    sp.set_defaults(func=cmd_triage_merge)

    sp = sub.add_parser("triage-render", help="重渲染台账")
    common(sp)
    sp.set_defaults(func=cmd_triage_render)

    sp = sub.add_parser("status", help="系列状态")
    common(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("fix-record", help="登记新 fix commit")
    common(sp)
    sp.add_argument("--sha", required=True)
    sp.add_argument("--target-seq", type=int, required=True)
    sp.add_argument("--origin", required=True, help="来源(如 r0-003)")
    sp.add_argument("--item", default=None, help="同时回填台账 item")
    sp.set_defaults(func=cmd_fix_record)

    sp = sub.add_parser("fix-associate", help="关联已有 fix 到台账 item")
    common(sp)
    sp.add_argument("--item", required=True)
    sp.add_argument("--sha", required=True)
    sp.set_defaults(func=cmd_fix_associate)

    sp = sub.add_parser("rebase-plan", help="生成 rebase todo(dry-run)")
    common(sp)
    sp.add_argument("--msg-file", action="append", metavar="SEQ=PATH",
                    help="patch seq -> 新 commit message 文件")
    sp.set_defaults(func=cmd_rebase_plan)

    sp = sub.add_parser("rebase-run", help="归档+备份+执行 rebase")
    common(sp)
    sp.add_argument("--msg-file", action="append", metavar="SEQ=PATH")
    sp.set_defaults(func=cmd_rebase_run)

    sp = sub.add_parser("export", help="导出最终系列")
    common(sp)
    sp.add_argument("--cover", default=None, help="cover 定稿路径(默认 cover/cover-vN.final.md)")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("send", help="铁律占位:永远拒绝(本工作流绝不发送 patch)")
    sp.add_argument("rest", nargs=argparse.REMAINDER,
                    help="任意参数一律忽略并拒绝")
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("resync", help="master 前移后重算")
    common(sp)
    sp.set_defaults(func=cmd_resync)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (SeriesError, FetchError, ImportError_, autosquash.RebaseError,
            gitops.GitError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
