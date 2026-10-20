"""pytest fixtures:临时 git 仓库(5 系列+2 fix)、小 mbox 工厂、v5 cover 裁剪件。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "tester@example.com",
    "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "tester@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00 +0000",
}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          capture_output=True, text=True, env=GIT_ENV)


def commit(repo: Path, msg: str, fixup: str | None = None) -> str:
    git(repo, "add", "-A")
    if fixup:
        git(repo, "commit", "--no-verify", f"--fixup={fixup}", "-q")
    else:
        git(repo, "commit", "--no-verify", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


class Repo:
    def __init__(self, path: Path):
        self.path = path
        self.base: str = ""
        self.series: list[str] = []   # 5 个系列 commit(从旧到新)
        self.fixes: list[str] = []    # 2 个 fix(都挤 series[1])

    def rev_list(self, ref: str = "HEAD") -> list[str]:
        return [l for l in git(self.path, "rev-list", "--reverse",
                               f"{self.base}..{ref}").stdout.splitlines() if l]


@pytest.fixture
def git_repo(tmp_path: Path) -> Repo:
    """base + 5 系列 commit(f1..f5 各自文件)+ 2 个 fix(都改 f2,挤 series[1])。"""
    repo = Repo(tmp_path / "repo")
    repo.path.mkdir(parents=True)
    git(repo.path, "init", "-q", "-b", "main")
    (repo.path / "f0.txt").write_text("base\n")
    repo.base = commit(repo.path, "base")
    for i in range(1, 6):
        (repo.path / f"f{i}.txt").write_text(f"series-{i}\n")
        repo.series.append(commit(repo.path, f"series-{i}"))
    # fix1/fix2 都针对 series[1](seq 2):普通 commit(import 场景)
    (repo.path / "f2.txt").write_text("series-2\nfix-a\n")
    f1 = commit(repo.path, "fix a for series-2")
    (repo.path / "f2.txt").write_text("series-2\nfix-a\nfix-b\n")
    f2 = commit(repo.path, "fix b for series-2")
    repo.fixes = [f1, f2]
    return repo


# ---------------------------------------------------------------- mbox

def make_mbox(path: Path, msgs: list[dict]) -> Path:
    """按给定邮件列表拼一个线程 mbox(From 分隔行 + 基本头 + 正文)。"""
    parts = []
    for m in msgs:
        head = [f"From: {m['from_']}", f"Subject: {m['subject']}",
                f"Message-ID: {m['msgid']}", f"Date: {m.get('date', 'Mon, 5 Oct 2026 10:00:00 +0000')}"]
        if m.get("irt"):
            head.append(f"In-Reply-To: {m['irt']}")
        if m.get("refs"):
            head.append(f"References: {' '.join(m['refs'])}")
        sep_date = m.get("date", "Mon, 5 Oct 2026 10:00:00 +0000")
        parts.append(f"From {m['msgid'].strip('<>')} {sep_date}\n"
                     + "\n".join(head) + "\n\n" + m["body"] + "\n\n")
    path.write_text("".join(parts), encoding="utf-8")
    return path


@pytest.fixture
def thread_mbox(tmp_path: Path) -> Path:
    """cover + 3 patch + 人类 review(patch1)+ sashiko(patch2 直接回复)
    + bot(patch3,References 间接)+ 嵌套人类回复(挂 sashiko 下)+ 作者回复。"""
    return make_mbox(tmp_path / "thread.mbox", [
        {"from_": "T Tian <t@example.com>",
         "subject": "[PATCH v5 00/3] test series", "msgid": "<cover@example.com>",
         "body": "cover body\n\n[1] https://lore.kernel.org/all/cover@example.com/\n\nSigned-off-by: T <t@example.com>"},
        {"from_": "T Tian <t@example.com>",
         "subject": "[PATCH v5 1/3] first", "msgid": "<p1@example.com>",
         "irt": "<cover@example.com>", "refs": ["<cover@example.com>"],
         "body": "first\n\nSigned-off-by: T <t@example.com>\n---\ndiff --git a/f1 b/f1\n"},
        {"from_": "T Tian <t@example.com>",
         "subject": "[PATCH v5 2/3] second", "msgid": "<p2@example.com>",
         "irt": "<cover@example.com>", "refs": ["<cover@example.com>"],
         "body": "second\n\nSigned-off-by: T <t@example.com>\n---\ndiff --git a/f2 b/f2\n"},
        {"from_": "T Tian <t@example.com>",
         "subject": "[PATCH v5 3/3] third", "msgid": "<p3@example.com>",
         "irt": "<cover@example.com>", "refs": ["<cover@example.com>"],
         "body": "third\n\nSigned-off-by: T <t@example.com>\n---\ndiff --git a/f3 b/f3\n"},
        {"from_": "Marc Zyngier <maz@kernel.org>",
         "subject": "Re: [PATCH v5 1/3] first", "msgid": "<rev1@kernel.org>",
         "irt": "<p1@example.com>", "refs": ["<cover@example.com>", "<p1@example.com>"],
         "body": "On patch 1: the foo is wrong, please fix bar."},
        {"from_": "sashiko-bot@kernel.org",
         "subject": "Re: [PATCH v5 2/3] second", "msgid": "<sash1@kernel.org>",
         "irt": "<p2@example.com>", "refs": ["<cover@example.com>", "<p2@example.com>"],
         "body": "Sashiko AI review found 1 issue: the baz leaks."},
        {"from_": "kernel test robot <oliver.sang@intel.com>",
         "subject": "Re: [PATCH v5 3/3] third", "msgid": "<bot1@intel.com>",
         "refs": ["<cover@example.com>", "<p3@example.com>"],
         "body": "kernel test robot: build error in f3.c"},
        {"from_": "Marc Zyngier <maz@kernel.org>",
         "subject": "Re: [PATCH v5 2/3] second", "msgid": "<rev2@kernel.org>",
         "irt": "<sash1@kernel.org>", "refs": ["<p2@example.com>", "<sash1@kernel.org>"],
         "body": "Reply nested under the sashiko comment."},
        {"from_": "T Tian <t@example.com>",
         "subject": "Re: [PATCH v5 1/3] first", "msgid": "<author1@example.com>",
         "irt": "<rev1@kernel.org>", "refs": ["<p1@example.com>", "<rev1@kernel.org>"],
         "body": "Thanks, will fix in v6."},
    ])


# ---------------------------------------------------------------- cover

V5_COVER = """From aaaabbbbccccdddd Mon Sep 17 00:00:00 2001
From: T Tian <t@example.com>
Date: Mon, 5 Oct 2026 10:00:00 +0000
Subject: [PATCH v5 00/3] test series for cover parse

This series implements a test feature, see RFC [1].

Comments welcome.

Changes since v4 [2]:

- Did A.
- Did B.

Changes since v3 [3]:

- Did C.

[1] https://lore.kernel.org/all/rfc@example.com/
[2] https://lore.kernel.org/all/v4@example.com/
[3] https://lore.kernel.org/all/v3@example.com/

Signed-off-by: T Tian <t@example.com>

T Tian (3):
  first
  second
  third

 f1 | 1 +
 1 file changed, 1 insertion(+)

base-commit: 1111222233334444555566667777888899990000
"""


@pytest.fixture
def v5_cover(tmp_path: Path) -> Path:
    p = tmp_path / "v5-0000-cover-letter.patch"
    p.write_text(V5_COVER, encoding="utf-8")
    return p
