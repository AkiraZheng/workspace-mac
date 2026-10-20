"""lore.kernel.org 拉取层。

优先 b4 mbox(证书正常的环境);b4 失败(如 lore 证书未生效/网络拦截)时
降级为 curl -k 直拉线程 mbox(公开邮件数据,内容不可信面已由上游
triage 流程的只读边界兜住)。也支持 --mbox-file 手动导入离线文件。
"""

from __future__ import annotations

import gzip
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

LORE_BASE = "https://lore.kernel.org/all"


class FetchError(RuntimeError):
    pass


def lore_url(msgid: str) -> str:
    msgid = msgid.strip().strip("<>")
    return f"{LORE_BASE}/{msgid}/"


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _fetch_via_b4(msgid: str, out_path: Path, timeout: int) -> bool:
    """b4 mbox 拉取线程,成功则落到 out_path。"""
    with tempfile.TemporaryDirectory(prefix="afu-b4-") as td:
        proc = _run(["b4", "mbox", "-o", td, msgid], timeout=timeout)
        if proc.returncode != 0:
            return False
        mbxes = sorted(Path(td).glob("*.mbx")) + sorted(Path(td).glob("*.mbox"))
        if not mbxes:
            return False
        shutil.copyfile(mbxes[0], out_path)
        return True


def _fetch_via_curl(msgid: str, out_path: Path, timeout: int) -> bool:
    """curl -k 直拉 <msgid>/t.mbox.gz(lore 证书异常时的兜底,跳过校验)。"""
    url = f"{lore_url(msgid)}t.mbox.gz"
    proc = subprocess.run(
        ["curl", "-kfsSL", "--max-time", str(timeout), url],
        capture_output=True, timeout=timeout + 30)  # 二进制:gzip 输出不能按文本解码
    if proc.returncode != 0 or not proc.stdout:
        return False
    data = proc.stdout
    try:
        text = gzip.decompress(data)
    except OSError:  # 未压缩的 mbox 直接返回
        text = data
    out_path.write_bytes(text)
    return True


def fetch_thread(msgid: str, out_path: Path, timeout: int = 300) -> str:
    """拉取 msgid 所属的完整线程 mbox 到 out_path,返回使用的模式。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    msgid = msgid.strip()
    if not (msgid.startswith("<") and msgid.endswith(">")):
        msgid = f"<{msgid}>"
    if _fetch_via_b4(msgid, out_path, timeout):
        return "b4"
    if _fetch_via_curl(msgid, out_path, timeout):
        return "curl"
    raise FetchError(
        f"线程拉取失败: b4 与 curl 均不可用 (msgid={msgid})。\n"
        f"兜底: 手动下载 {lore_url(msgid)}t.mbox.gz 后用 --mbox-file 导入")


def import_mbox_file(src: Path, out_path: Path) -> str:
    """离线导入:把手动下载的线程 mbox 作为本轮快照。"""
    src = Path(src)
    if not src.is_file():
        raise FetchError(f"mbox 文件不存在: {src}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".gz":
        out_path.write_bytes(gzip.decompress(src.read_bytes()))
    else:
        shutil.copyfile(src, out_path)
    return "file"


MSGID_RE = re.compile(r"^<[^<>]+>$")


def normalize_msgid(value: str | None) -> str | None:
    """统一 Message-ID 为 <...> 形式;空/畸形返回 None。"""
    if not value:
        return None
    v = " ".join(value.split())
    if not v.startswith("<"):
        v = f"<{v}>"
    return v if MSGID_RE.match(v) else None
