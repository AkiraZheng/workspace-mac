#!/usr/bin/env python3
"""Unified patchset download script.

Handles three input types:
  - message-id  → b4 am <msg-id> -o <output-dir>
  - URL          → wget download
  - local path   → copy .patch files to output-dir
"""

from __future__ import annotations

import os
import re
import sys
import json
import shutil
import subprocess
import argparse


def detect_source_type(source: str) -> str:
    """Classify input source as message-id, url, or local path."""
    if re.match(r"^<.*@.*>$", source.strip()):
        return "message-id"
    if source.startswith(("http://", "https://")):
        return "url"
    if os.path.exists(source):
        return "local"
    raise ValueError(
        f"Cannot classify input source: {source}. "
        f"Expected message-id (<...@...>), URL (https://...), or local path."
    )


def detect_proxy() -> str | None:
    """Detect proxy from environment variables."""
    for var in (
        "https_proxy", "HTTPS_PROXY",
        "http_proxy", "HTTP_PROXY",
        "all_proxy", "ALL_PROXY",
    ):
        proxy = os.environ.get(var)
        if proxy:
            return proxy
    return None


def download_via_b4(
    message_id: str, output_dir: str, proxy: str | None = None
) -> list[str]:
    """Download patchset using b4."""
    os.makedirs(output_dir, exist_ok=True)
    cmd = ["b4", "am", message_id, "-o", output_dir]
    env = os.environ.copy()
    if proxy:
        for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
            env[key] = proxy
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, env=env, timeout=120
        )
    except FileNotFoundError:
        raise RuntimeError("b4 is not installed. Install with: pip install b4")
    if result.returncode != 0:
        raise RuntimeError(f"b4 download failed: {result.stderr.strip()}")
    return sorted(
        f for f in (os.path.join(output_dir, x) for x in os.listdir(output_dir))
        if f.endswith(".patch")
    )


def download_via_url(
    url: str, output_dir: str, proxy: str | None = None
) -> list[str]:
    """Download patchset from URL using wget."""
    os.makedirs(output_dir, exist_ok=True)
    cmd = ["wget", "-nv", "-P", output_dir]
    if proxy:
        cmd.extend([
            "-e", "use_proxy=on",
            "-e", f"https_proxy={proxy}",
            "-e", f"http_proxy={proxy}",
        ])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise RuntimeError("wget is not installed.")
    if result.returncode != 0:
        raise RuntimeError(f"URL download failed: {result.stderr.strip()}")
    return sorted(
        f for f in (os.path.join(output_dir, x) for x in os.listdir(output_dir))
        if f.endswith(".patch")
    )


def mbox_to_patches(mbox_path: str, output_dir: str) -> list[str]:
    """Convert .mbox file(s) to individual .patch files.

    Supports single .mbox and directory of .mbox files.
    When a directory contains both combined and individual .mbox files,
    uses only the combined one.
    """
    results = []

    if os.path.isfile(mbox_path):
        mbox_files = [mbox_path]
    elif os.path.isdir(mbox_path):
        all_mbox = sorted([
            os.path.join(mbox_path, f) for f in os.listdir(mbox_path)
            if f.endswith(".mbox")
        ])
        if not all_mbox:
            return results
        # 如果有组合 mbox（size > 50KB），只使用它
        combined = [f for f in all_mbox if os.path.getsize(f) > 50_000]
        mbox_files = combined if combined else all_mbox
    else:
        return results

    for mbox_file in mbox_files:
        with open(mbox_file, errors="replace") as f:
            content = f.read()

        # Split combined mbox by "From " markers
        parts = re.split(r'^(?=From \S+ )', content, flags=re.MULTILINE)
        if not parts or not parts[0].strip():
            parts = parts[1:] if len(parts) > 1 else []

        # If no "From " markers found, treat as single patch
        if not parts:
            parts = [content]

        # Only keep parts that look like patches (contain diff markers)
        valid_parts = [p for p in parts
                       if "Subject:" in p and ("diff --git" in p or "---" in p)]

        seen_subjects = set()
        patch_idx = 0
        for part in valid_parts:
            subject = ""
            for line in part.split("\n"):
                if line.startswith("Subject:"):
                    subject = line.replace("Subject:", "").strip()
                    subject = re.sub(r'\[PATCH[^\]]*\]\s*', '', subject)
                    break

            if not subject:
                continue

            # 跳过回复（Re:）和重复 subject
            if subject.startswith("Re:") or subject.startswith("Re："):
                continue

            key = sanitize_filename(subject)
            if key in seen_subjects:
                continue
            seen_subjects.add(key)
            patch_idx += 1

            fname = generate_output_name(patch_idx, subject)
            dest = os.path.join(output_dir, fname)
            with open(dest, "w") as out:
                out.write(part)
            results.append(dest)

    return results


def _extract_subject(patch_path: str) -> str:
    """Extract the Subject line from a .patch file."""
    try:
        with open(patch_path, errors="replace") as f:
            for line in f:
                if line.startswith("Subject:"):
                    s = line.replace("Subject:", "").strip()
                    s = re.sub(r'\[PATCH[^\]]*\]\s*', '', s)
                    return s.strip()
    except (FileNotFoundError, IOError):
        pass
    return os.path.basename(patch_path).replace(".patch", "")


def copy_from_local(source_path: str, output_dir: str) -> list[str]:
    """Copy .patch/.mbox files from local directory to output directory."""
    os.makedirs(output_dir, exist_ok=True)
    results = []

    # Handle .mbox files first
    if (os.path.isfile(source_path) and source_path.endswith(".mbox")) or \
       (os.path.isdir(source_path) and any(
           f.endswith(".mbox") for f in os.listdir(source_path))):
        results.extend(mbox_to_patches(source_path, output_dir))

    # Handle .patch files
    if os.path.isfile(source_path) and source_path.endswith(".patch"):
        subject = _extract_subject(source_path)
        fname = generate_output_name(1, subject)
        dest = os.path.join(output_dir, fname)
        shutil.copy2(source_path, dest)
        results.append(dest)
    elif os.path.isdir(source_path):
        patch_files = sorted(
            [f for f in os.listdir(source_path) if f.endswith(".patch")],
        )
        for idx, fname in enumerate(patch_files, start=1):
            src = os.path.join(source_path, fname)
            subject = _extract_subject(src)
            new_fname = generate_output_name(idx, subject)
            dest = os.path.join(output_dir, new_fname)
            shutil.copy2(src, dest)
            results.append(dest)

    return results


def pad_patch_number(n: int) -> str:
    """Zero-pad patch number to 4 digits."""
    return f"{n:04d}"


def sanitize_filename(subject: str) -> str:
    """Replace special chars in subject for safe filename."""
    result = subject
    for ch in r'<>:"/\|?*':
        result = result.replace(ch, "-")
    result = result.replace(" ", "-")
    result = re.sub(r"-{2,}", "-", result)
    return result.strip("-")


def generate_output_name(index: int, subject: str) -> str:
    """Generate output filename: 0001-Sanitized-Subject.patch."""
    return f"{pad_patch_number(index)}-{sanitize_filename(subject)}.patch"


def generate_metadata(
    source: str,
    method: str,
    total: int,
    target_kernel: str,
    target_branch: str,
    build_target: str,
    patches: list[dict],
) -> dict:
    """Generate patchset.metadata.json structure."""
    return {
        "source": source,
        "download_method": method,
        "total_patches": total,
        "target_kernel": target_kernel,
        "target_branch": target_branch,
        "build_target": build_target,
        "patches": patches,
    }


def main():
    parser = argparse.ArgumentParser(description="Download Linux kernel patchset")
    parser.add_argument(
        "--source", required=True,
        help="message-id / URL / local path",
    )
    parser.add_argument(
        "--output-dir", default="/tmp/patches/",
        help="output directory",
    )
    parser.add_argument(
        "--proxy", default=None,
        help="HTTP proxy (auto-detected if absent)",
    )
    parser.add_argument(
        "--target-kernel", default=os.environ.get("KERNEL_REPO_PATH"),
        help="target kernel repo path (or set KERNEL_REPO_PATH env var)",
    )
    parser.add_argument(
        "--target-branch", default=os.environ.get("KERNEL_BRANCH"),
        help="target branch (or set KERNEL_BRANCH env var)",
    )
    parser.add_argument(
        "--build-target", default=os.environ.get("BUILD_CMD"),
        help="build command (or set BUILD_CMD env var)",
    )
    args = parser.parse_args()

    missing = []
    if not args.target_kernel:
        missing.append("--target-kernel (or KERNEL_REPO_PATH)")
    if not args.target_branch:
        missing.append("--target-branch (or KERNEL_BRANCH)")
    if not args.build_target:
        args.build_target = "make -j$(nproc)"
    if missing:
        print(f"错误: 缺少必要参数: {', '.join(missing)}")
        print("请通过 CLI 参数或环境变量提供。")
        sys.exit(1)

    source_type = detect_source_type(args.source)
    proxy = args.proxy or detect_proxy()

    if proxy:
        print(f"[INFO] Using proxy: {proxy}")

    if source_type == "message-id":
        print(f"[INFO] Downloading via b4: {args.source}")
        patch_files = download_via_b4(args.source, args.output_dir, proxy)
    elif source_type == "url":
        print(f"[INFO] Downloading via URL: {args.source}")
        patch_files = download_via_url(args.source, args.output_dir, proxy)
    elif source_type == "local":
        print(f"[INFO] Copying from local: {args.source}")
        patch_files = copy_from_local(args.source, args.output_dir)

    if not patch_files:
        print("[ERROR] No .patch or .mbox files found.")
        sys.exit(1)

    print(f"[OK] Downloaded {len(patch_files)} patch files.")
    for f in patch_files:
        print(f"  {f}")

    patches_meta = []
    for idx, pf in enumerate(patch_files, 1):
        patches_meta.append({
            "id": pad_patch_number(idx),
            "file": pf,
            "subject": "",
            "author": "",
            "date": "",
            "upstream_commit": "",
        })

    metadata = generate_metadata(
        source=args.source,
        method=source_type,
        total=len(patch_files),
        target_kernel=args.target_kernel,
        target_branch=args.target_branch,
        build_target=args.build_target,
        patches=patches_meta,
    )

    metadata_path = os.path.join(args.output_dir, "patchset.metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"[OK] Metadata written to {metadata_path}")


if __name__ == "__main__":
    main()
