"""从 lore.kernel.org 下载完整 patchset"""
import subprocess
import hashlib
from pathlib import Path

def download_patchset(patch_url: str, output_dir: Path) -> tuple[Path, str]:
    """
    使用 b4 am 下载完整 patchset mbox 文件
    Returns: (mbox_path, mbox_hash)
    """
    result = subprocess.run(
        ['b4', 'am', patch_url],
        cwd=output_dir,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"b4 am failed: {result.stderr}")

    # 查找生成的 mbox 文件
    mbox_files = list(output_dir.glob("*.mbox"))
    if not mbox_files:
        raise RuntimeError("No mbox file generated")

    mbox_path = mbox_files[0]
    mbox_hash = hashlib.sha256(mbox_path.read_bytes()).hexdigest()

    return mbox_path, mbox_hash
