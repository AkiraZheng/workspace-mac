#!/usr/bin/env python3
"""
L1 确定性脚本：从 .patch 文件提取符号和元数据，生成 analysis_cache.json 骨架。

提取内容：
  - introduced_symbols: patch 新增/修改的函数名、宏名、结构体名、类型名
  - referenced_symbols: patch 调用/引用的外部符号
  - 功能分类: 按文件路径 + diff 内容判定
  - feature_signature: 关键词 + 涉改目录（从 patch 路径推断）
  - changed_files: 涉改文件列表

输出: analysis_cache.json（按 patch task_id 组织的结构化数据）
"""

import argparse
import json
import os
import re
import sys


def extract_from_patch(patch_file: str) -> dict:
    result = {
        "subject": "",
        "introduced_symbols": [],
        "referenced_symbols": [],
        "changed_files": [],
        "功能分类": "core",
        "feature_signature": {"keywords": [], "scope_dirs": []},
    }

    try:
        with open(patch_file, 'r') as f:
            content = f.read()
    except Exception:
        return result

    lines = content.split('\n')
    current_file = ""
    all_files = set()
    add_lines = []
    header_done = False
    in_diff = False

    for line in lines:
        if not header_done:
            m = re.match(r'^Subject:\s*(.+)', line)
            if m:
                result["subject"] = m.group(1).strip()
                header_done = True
            continue

        m = re.match(r'^\+\+\+\s+b/(.+)', line)
        if m:
            current_file = m.group(1)
            if current_file not in ('/dev/null', ''):
                all_files.add(current_file)
            in_diff = True
            continue

        if in_diff and line.startswith('+') and not line.startswith('+++'):
            add_lines.append(line[1:].strip())

    result["changed_files"] = sorted(all_files)

    introduced = set()
    referenced = set()

    for line in add_lines:
        m = re.match(r'^(static\s+)?(inline\s+)?(\w+[\s*]+)+(\w+)\s*\(', line)
        if m:
            introduced.add(m.group(4).strip())

        m = re.match(r'^#define\s+(\w+)', line)
        if m:
            introduced.add(m.group(1))

        m = re.match(r'^(struct|union|enum)\s+(\w+)', line)
        if m:
            introduced.add(m.group(2))

        m = re.match(r'^typedef\s+.+\s+(\w+)\s*;', line)
        if m:
            introduced.add(m.group(1))

        for match in re.finditer(r'\b(\w+)\s*\(', line):
            name = match.group(1)
            if name not in introduced:
                referenced.add(name)

        for match in re.finditer(r'\b([A-Z][A-Z0-9_]{3,})\b', line):
            macro = match.group(1)
            if macro not in introduced:
                referenced.add(macro)

    noise = {"void", "int", "char", "long", "short", "unsigned", "signed",
             "const", "static", "inline", "extern", "volatile", "register",
             "bool", "size_t", "u8", "u16", "u32", "u64", "s8", "s16",
             "s32", "s64", "phys_addr_t", "gfp_t", "pgd_t", "pud_t",
             "pmd_t", "pte_t", "spinlock_t", "NULL", "true", "false",
             "if", "while", "for", "switch", "return", "sizeof", "typeof"}
    introduced -= noise
    referenced -= noise

    result["introduced_symbols"] = sorted(introduced)
    result["referenced_symbols"] = sorted(referenced)
    result["功能分类"] = _classify(all_files, add_lines, result["subject"])

    keywords, scope_dirs = _extract_signature(add_lines, all_files, result["subject"])
    result["feature_signature"]["keywords"] = sorted(keywords)
    result["feature_signature"]["scope_dirs"] = sorted(scope_dirs)

    return result


def _classify(files: set, add_lines: list, subject: str) -> str:
    for f in files:
        if any(f.startswith(p) for p in (
            "include/linux/", "include/uapi/", "arch/", "tools/include/"
        )):
            define_count = sum(1 for l in add_lines if l.startswith("#define"))
            typedef_count = sum(1 for l in add_lines if l.startswith("typedef"))
            struct_count = sum(1 for l in add_lines if l.startswith("struct "))
            total = len(add_lines) if add_lines else 1
            if (define_count + typedef_count + struct_count) / total > 0.3:
                return "infra"
        if f.startswith("Documentation/"):
            return "doc"
        if f.startswith("sound/"):
            return "sound"
        if f.startswith("net/"):
            return "net"
        if f.startswith("fs/"):
            return "fs"
        if f.startswith("drivers/"):
            return "driver"
        if any(f.startswith(p) for p in ("kernel/", "mm/", "init/")):
            return "core"

    sl = subject.lower()
    if any(kw in sl for kw in ("fix", "bug", "error", "patch")):
        return "bugfix"
    if any(kw in sl for kw in ("doc", "comment", "documentation")):
        return "doc"

    return "core"


def _extract_signature(add_lines: list, files: set, subject: str) -> tuple:
    keywords = set()
    scope_dirs = set()

    for line in [subject] + add_lines[:50]:
        for match in re.finditer(r'\b([A-Z][A-Z0-9_]{2,})\b', line):
            kw = match.group(1)
            if kw not in ("NULL", "BUG", "TODO", "FIXME", "GPL",
                          "ARCH", "CONFIG", "BIT", "GENMASK", "FIELD_PREP",
                          "FIELD_GET", "SYSREG", "ARM", "ARM64", "KVM"):
                keywords.add(kw)

    for f in files:
        parts = f.split('/')
        if len(parts) >= 2:
            scope_dirs.add('/'.join(parts[:2]) + '/')
    if not scope_dirs:
        for f in files:
            parts = f.split('/')
            if parts:
                scope_dirs.add(parts[0] + '/')

    return keywords, scope_dirs


def main():
    parser = argparse.ArgumentParser(description='从 patch 文件提取符号和元数据')
    parser.add_argument('--patch-dir', required=True, help='patch 文件目录')
    parser.add_argument('--output', required=True, help='输出 analysis_cache.json 路径')
    args = parser.parse_args()

    patch_dir = args.patch_dir
    if not os.path.isdir(patch_dir):
        print(f"错误: 目录不存在: {patch_dir}", file=sys.stderr)
        sys.exit(1)

    patch_files = sorted([
        f for f in os.listdir(patch_dir)
        if f.endswith('.patch') and f.startswith('0')
    ])

    if not patch_files:
        print(f"警告: {patch_dir} 中无 .patch 文件", file=sys.stderr)
        sys.exit(1)

    cache = {}
    for pf in patch_files:
        task_id = pf[:4]
        full_path = os.path.join(patch_dir, pf)
        entry = extract_from_patch(full_path)
        entry["patch_file"] = full_path
        cache[task_id] = entry

    with open(args.output, 'w') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(f"[extract_patch_symbols] {len(cache)} patches -> {args.output}")
    for tid, e in cache.items():
        print(f"  {tid}: {e['功能分类']:<8} "
              f"intro={len(e['introduced_symbols']):>2} "
              f"ref={len(e['referenced_symbols']):>2} "
              f"files={len(e['changed_files'])}")


if __name__ == '__main__':
    main()
