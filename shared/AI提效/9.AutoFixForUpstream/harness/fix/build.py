"""编译验证:跑 build command + 产物存在性检查,日志落盘 build/。"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BuildResult:
    ok: bool
    cmd: str
    returncode: int
    duration_s: float
    log_path: Path
    artifact_ok: bool


def run_build(command: str, artifact: str, log_dir: Path,
              cwd: Path, timeout: int = 3600) -> BuildResult:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"build-{stamp}.log"
    start = time.time()
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"# cmd: {command}\n# cwd: {cwd}\n\n")
        log.flush()
        try:
            proc = subprocess.run(
                ["bash", "-c", command], cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = -1
            log.write(f"\n# TIMEOUT after {timeout}s\n")
    duration = time.time() - start
    artifact_ok = (cwd / artifact).exists() if artifact else True
    return BuildResult(ok=(rc == 0 and artifact_ok), cmd=command, returncode=rc,
                       duration_s=duration, log_path=log_path, artifact_ok=artifact_ok)


def tail_errors(log_path: Path, max_lines: int = 60) -> str:
    """取日志尾部的错误上下文(供 LLM 诊断)。"""
    lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    idx = [i for i, l in enumerate(lines) if "error:" in l or "Error" in l]
    start = max(0, (idx[-1] if idx else len(lines)) - max_lines)
    return "\n".join(lines[start:start + max_lines])
