#!/usr/bin/env python3
"""Unified patchset download script.

Handles three input types:
  - message-id  → b4 am <msg-id> -o <output-dir>
  - URL          → wget download
  - local path   → copy .patch files to output-dir

Supports mbox format conversion:
  - Converts .mbox files to standard .patch format
  - Extracts From, Subject, Date, commit message, diff
  - Removes email headers (To, Cc, Message-ID, References, etc.)
"""

from __future__ import annotations

import os
import re
import sys
import json
import shutil
import subprocess
import argparse
from pathlib import Path
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage


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


def convert_mbox_to_patch(mbox_file: str, patch_file: str) -> bool:
    """Convert mbox file to standard git patch format.
    
    Args:
        mbox_file: Path to input .mbox file
        patch_file: Path to output .patch file
    
    Returns:
        True if conversion successful, False otherwise
    
    Converts mbox format (with email headers) to standard patch format:
        - Extracts: From, Subject, Date, commit message, diff
        - Removes: To, Cc, Message-ID, References, In-Reply-To, etc.
        - Preserves: diff --git sections intact
    """
    try:
        with open(mbox_file, 'rb') as f:
            msg: EmailMessage = BytesParser(policy=policy.default).parse(f)
        
        # Extract core headers
        from_header = msg.get('From', '')
        subject = msg.get('Subject', '')
        date_header = msg.get('Date', '')
        
        # Extract body (commit message + diff)
        body = msg.get_body(preferencelist=('plain',))
        if body is None:
            # Fallback: try to extract content manually
            content = msg.get_content()
        else:
            content = body.get_content()
        
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        
        # Find diff section start
        lines = content.split('\n')
        diff_start = None
        for i, line in enumerate(lines):
            if line.startswith('diff --git'):
                diff_start = i
                break
        
        # Split content: commit message (before diff) and diff section
        if diff_start is not None:
            commit_msg_lines = lines[:diff_start]
            diff_lines = lines[diff_start:]
        else:
            # No diff found, treat entire content as commit message
            commit_msg_lines = lines
            diff_lines = []
        
        # Clean commit message: remove email headers from body
        cleaned_commit_msg = []
        for line in commit_msg_lines:
            # Skip email header lines in body (To:, Cc:, etc.)
            if re.match(r'^[A-Z][a-zA-Z-]+:\s*', line):
                continue
            # Skip empty lines at start/end
            cleaned_commit_msg.append(line)
        
        # Trim leading/trailing empty lines
        while cleaned_commit_msg and not cleaned_commit_msg[0].strip():
            cleaned_commit_msg.pop(0)
        while cleaned_commit_msg and not cleaned_commit_msg[-1].strip():
            cleaned_commit_msg.pop()
        
        # Build output patch
        output_lines = []
        
        # Add From header (if present)
        if from_header:
            output_lines.append(f"From: {from_header}")
            output_lines.append('')
        
        # Add Subject (if present)
        if subject:
            output_lines.append(subject)
            output_lines.append('')
        
        # Add commit message (limit to 20 lines for reasonable size)
        if cleaned_commit_msg:
            output_lines.extend(cleaned_commit_msg[:20])
            output_lines.append('')
        
        # Add diff section (intact)
        if diff_lines:
            output_lines.extend(diff_lines)
        
        # Write output
        Path(patch_file).write_text('\n'.join(output_lines), encoding='utf-8')
        return True
    
    except Exception as e:
        print(f"⚠️ mbox conversion failed: {e}")
        # Fallback: simple copy with filename change
        shutil.copy2(mbox_file, patch_file)
        return False


def copy_from_local(source_path: str, output_dir: str) -> list[str]:
    """Copy .patch / .mbox files from local directory to output directory.
    
    Converts .mbox files to .patch format using convert_mbox_to_patch.
    """
    os.makedirs(output_dir, exist_ok=True)
    results = []
    
    # Handle single file
    if os.path.isfile(source_path):
        if source_path.endswith(".patch"):
            # Direct copy for .patch files
            basename = os.path.basename(source_path)
            dest = os.path.join(output_dir, basename)
            shutil.copy2(source_path, dest)
            results.append(dest)
        
        elif source_path.endswith(".mbox"):
            # Convert .mbox to .patch
            basename = os.path.basename(source_path).replace(".mbox", ".patch")
            dest = os.path.join(output_dir, basename)
            
            if convert_mbox_to_patch(source_path, dest):
                print(f"✅ Converted mbox: {source_path} → {dest}")
                results.append(dest)
            else:
                print(f"⚠️ mbox conversion failed, fallback to copy")
                results.append(dest)
    
    # Handle directory
    elif os.path.isdir(source_path):
        for fname in sorted(os.listdir(source_path)):
            if fname.endswith(".patch"):
                src = os.path.join(source_path, fname)
                dest = os.path.join(output_dir, fname)
                shutil.copy2(src, dest)
                results.append(dest)
            
            elif fname.endswith(".mbox"):
                src = os.path.join(source_path, fname)
                dest = os.path.join(output_dir, fname.replace(".mbox", ".patch"))
                
                if convert_mbox_to_patch(src, dest):
                    print(f"✅ Converted mbox: {src} → {dest}")
                    results.append(dest)
                else:
                    print(f"⚠️ mbox conversion failed: {src}")
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
        print("[ERROR] No .patch files found.")
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
