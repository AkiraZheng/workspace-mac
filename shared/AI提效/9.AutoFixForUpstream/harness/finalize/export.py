"""finalize 的导出层:format-patch 骨架 + cover splice。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from harness.common import gitops
from harness.cover.render import splice_into_format_patch


def export_series(repo: Path, base: str, version: int, cover_final: Path,
                  out_dir: Path) -> list[Path]:
    """git format-patch -vN --cover-letter --base=<base> 生成骨架并拼接 cover。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = gitops.run_git(
        repo, "format-patch",
        f"--subject-prefix=PATCH v{version}",
        "--cover-letter", f"--base={base}", "-o", str(out_dir), f"{base}..HEAD")
    patches = sorted(out_dir.glob("*.patch"))
    if not patches or not patches[0].name.startswith("0000-"):
        raise RuntimeError(f"format-patch 输出异常: {[p.name for p in patches]}")
    splice_into_format_patch(cover_final, patches[0])
    return patches
