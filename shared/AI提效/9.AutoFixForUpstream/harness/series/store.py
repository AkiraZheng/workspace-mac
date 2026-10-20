"""系列工作区:<repo>/.autofix/<series-id>/ 的读写与状态迁移(唯一写者)。

目录布局:
    series.yaml   静态配置(模板拷贝)
    state.json    动态状态(schema 校验)
    triage.json   检视意见台账(schema 校验)
    triage.md     台账渲染(可再生)
    mboxes/       v5/(b4 am 产物) + round-NNNN.mbox + round-NNNN/*.eml
    reviews/      round-N/item-*.json + .md(LLM 产物,triage-merge 并入)
    cover/        cover-vN.draft.md / cover-vN.final.md
    build/ final/ 编译与最终产物
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from harness.common import gitops
from harness.common.json_utils import read_json, validate, write_json

AUTOFIX_DIR = ".autofix"
PHASES = ("monitoring", "finalizing", "done")
TERMINAL_ITEM_STATUS = ("fixed", "invalid", "wontfix", "deferred", "record_only")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SeriesError(RuntimeError):
    pass


def autofix_root(repo_path: Path) -> Path:
    return Path(repo_path) / AUTOFIX_DIR


def list_series(repo_path: Path) -> list[str]:
    root = autofix_root(repo_path)
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if (d / "series.yaml").is_file())


def find_series(repo_path: Path, series_id: str | None = None) -> Path:
    """定位系列目录;repo 下只有一个系列时可省 series_id。"""
    ids = list_series(repo_path)
    if series_id is None:
        if len(ids) == 1:
            return autofix_root(repo_path) / ids[0]
        raise SeriesError(f"需要指明 series-id,当前 {len(ids)} 个系列: {ids or '无'}")
    if series_id not in ids:
        raise SeriesError(f"系列不存在: {series_id}(现有: {ids or '无'})")
    return autofix_root(repo_path) / series_id


def ensure_git_exclude(repo_path: Path) -> None:
    """把 .autofix/ 追加进内核仓库的 .git/info/exclude(不动 tracked .gitignore)。"""
    exclude = Path(repo_path) / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    body = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if AUTOFIX_DIR not in body:
        with exclude.open("a", encoding="utf-8") as f:
            if body and not body.endswith("\n"):
                f.write("\n")
            f.write(f"# autofix-upstream 系列工作区\n{AUTOFIX_DIR}/\n")


class SeriesStore:
    """一个系列工作区的读写入口。"""

    def __init__(self, series_dir: Path, require_state: bool = True):
        self.dir = Path(series_dir)
        self.cfg_path = self.dir / "series.yaml"
        self.state_path = self.dir / "state.json"
        self.ledger_path = self.dir / "triage.json"
        if not self.cfg_path.is_file():
            raise SeriesError(f"不是系列工作区: {self.dir}")
        self.cfg: dict = yaml.safe_load(self.cfg_path.read_text(encoding="utf-8"))
        self.repo = Path(self.cfg["repo_path"])
        if require_state and not self.state_path.is_file():
            raise SeriesError(f"state.json 缺失,系列未完成初始化: {self.dir}")

    # ---------- 创建 ----------

    @classmethod
    def create(cls, repo_path: Path, series_id: str, cfg: dict) -> "SeriesStore":
        root = autofix_root(repo_path)
        if (root / series_id / "series.yaml").exists():
            raise SeriesError(f"系列已存在: {series_id}")
        sdir = root / series_id
        for sub in ("mboxes", "reviews", "cover", "build", "final"):
            (sdir / sub).mkdir(parents=True, exist_ok=True)
        cfg = dict(cfg, series_id=series_id)
        (sdir / "series.yaml").write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        ensure_git_exclude(repo_path)
        return cls(sdir, require_state=False)

    # ---------- state ----------

    @property
    def state(self) -> dict:
        return read_json(self.state_path)

    def save_state(self, **updates: Any) -> dict:
        st = self.state
        st.update(updates, updated_at=now_iso())
        errors = validate(st, "state")
        if errors:
            raise SeriesError(f"state 违反 schema: {errors}")
        write_json(self.state_path, st)
        return st

    def require_phase(self, *phases: str) -> None:
        if self.state["phase"] not in phases:
            raise SeriesError(f"phase={self.state['phase']},要求 {'/'.join(phases)}")

    def init_state(self, base_commit: str, series_commits: list[dict],
                   fix_commits: list[dict], root_msgid: str, import_mode: bool) -> dict:
        if self.state_path.exists():
            raise SeriesError("state.json 已存在")
        v = self.cfg["prev_version"]
        st = {
            "schema_version": "1.0",
            "series_id": self.cfg["series_id"],
            "phase": "monitoring",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "import_mode": import_mode,
            "base": {"commit": base_commit, "subject": gitops.subject_of(self.repo, base_commit)},
            "series_commits": series_commits,
            "fix_commits": fix_commits,
            "cover": {
                "v5_msgid": self.cfg["prev_msgid"],
                "v5_lore_url": f"https://lore.kernel.org/all/{self.cfg['prev_msgid']}/",
                "draft": f"cover/cover-v{v + 1}.draft.md",
                "final": None,
            },
            "thread": {"root_msgid": root_msgid, "messages_seen": [], "rounds": []},
            "poll": {"last_run_at": None, "last_status": None},
            "final": {"started_at": None, "rebase": {"done": False, "old_to_new": {}},
                      "backup_branch": None, "export_dir": None},
        }
        errors = validate(st, "state")
        if errors:
            raise SeriesError(f"初始 state 违反 schema: {errors}")
        write_json(self.state_path, st)
        return st

    # ---------- ledger ----------

    @property
    def ledger(self) -> dict:
        if not self.ledger_path.is_file():
            return {"schema_version": "1.0", "items": []}
        return read_json(self.ledger_path)

    def save_ledger(self, items: list[dict]) -> dict:
        data = {"schema_version": "1.0", "items": items}
        errors = validate(data, "triage")
        if errors:
            raise SeriesError(f"台账违反 schema: {errors}")
        write_json(self.ledger_path, data)
        return data

    def items(self) -> list[dict]:
        return self.ledger["items"]

    def update_item(self, item_id: str, **fields: Any) -> dict:
        items = self.items()
        for it in items:
            if it["id"] == item_id:
                it.update(fields)
                self.save_ledger(items)
                return it
        raise SeriesError(f"台账无此 item: {item_id}")

    def record_fix(self, sha: str, target_seq: int, origin: str) -> dict:
        st = self.state
        for fx in st["fix_commits"]:
            if fx["sha"] == sha:
                raise SeriesError(f"fix commit 已登记: {sha}")
        st["fix_commits"].append({
            "sha": sha,
            "subject": gitops.subject_of(self.repo, sha),
            "target_seq": target_seq,
            "origin": origin,
        })
        self.save_state(fix_commits=st["fix_commits"])
        return st

    # ---------- 查询 ----------

    def pending_items(self) -> list[dict]:
        return [it for it in self.items() if it["status"] == "pending"]

    def fixable_items(self) -> list[dict]:
        return [it for it in self.items()
                if it["status"] == "analyzed" and it.get("verdict") == "valid"
                and it.get("fix_type") == "code"]

    def unresolved_items(self) -> list[dict]:
        return [it for it in self.items() if it["status"] not in TERMINAL_ITEM_STATUS]

    def status_dict(self) -> dict:
        st = self.state
        by: dict[str, int] = {}
        for it in self.items():
            key = f"{it['status']}/{it['source']['sender_class']}"
            by[key] = by.get(key, 0) + 1
        rounds = st["thread"]["rounds"]
        return {
            "series_id": st["series_id"],
            "phase": st["phase"],
            "branch": self.cfg["work_branch"],
            "base": st["base"]["commit"][:12],
            "patches": len(st["series_commits"]),
            "fixes": len(st["fix_commits"]),
            "rounds": len(rounds),
            "last_poll": st["poll"]["last_run_at"],
            "last_poll_status": st["poll"]["last_status"],
            "messages_seen": len(st["thread"]["messages_seen"]),
            "items_total": len(self.items()),
            "items_by_status": by,
            "pending": len(self.pending_items()),
            "fixable": len(self.fixable_items()),
            "unresolved": len(self.unresolved_items()),
            "last_round_at": rounds[-1]["at"] if rounds else None,
        }

    # ---------- 路径辅助 ----------

    def round_mbox(self, round_no: int) -> Path:
        return self.dir / "mboxes" / f"round-{round_no:04d}.mbox"

    def round_dir(self, round_no: int) -> Path:
        return self.dir / "mboxes" / f"round-{round_no:04d}"

    def reviews_dir(self, round_no: int) -> Path:
        return self.dir / "reviews" / f"round-{round_no}"

    def reset_workspace(self) -> None:
        """finalize 失败后的清理语义:仅回退 phase(分支回退由调用方负责)。"""
        self.save_state(phase="monitoring", **{
            "final": {"started_at": None, "rebase": {"done": False, "old_to_new": {}},
                      "backup_branch": None, "export_dir": None}})
