#!/usr/bin/env python3
"""抽样检测：提取关键代码行 + 输出待 grep 的命令

执行时间：<1s（只解析 patch 文件，不执行 git 命令）

抽样策略：
  1. 符号行（函数定义、宏定义、结构体定义）
  2. 关键行（包含大写关键词）
  3. 前5行（代表性代码）

输出：
  - samples_summary.json（供 AI 分析）
  - grep_commands.txt（供 Bash 并行执行）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def extract_samples(patch_path: Path) -> dict:
    """从 patch 文件中提取抽样代码行"""
    text = patch_path.read_text(errors='replace')
    task_id = patch_path.stem.split('-')[0]
    
    # 提取文件路径
    files = []
    for m in re.finditer(r'diff --git a/(\S+) b/', text):
        files.append(m.group(1))
    
    # 抽样策略：符号 + 关键词 + 前5行
    symbol_samples = []
    keyword_samples = []
    all_add_lines = []
    
    for line in text.split('\n'):
        if line.startswith('+') and not line.startswith('+++'):
            content = line[1:].strip()
            if content:
                all_add_lines.append(content)
                
                # 符号行（函数、宏、结构体）
                if re.match(r'(?:static\s+|inline\s+)?(?:\w+\s+)+\**(\w+)\s*\(', content):
                    symbol_samples.append(content)
                elif re.match(r'#define\s+(\w+)', content):
                    symbol_samples.append(content)
                elif re.match(r'(?:struct|enum|union)\s+(\w+)', content):
                    symbol_samples.append(content)
                
                # 大写关键词行
                elif re.search(r'\b[A-Z][A-Z0-9_]{2,}\b', content):
                    keyword_samples.append(content)
    
    # 补充：前5行（代表性代码）
    representative_samples = all_add_lines[:5]
    
    # 提取关键词（用于后续扩展搜索）
    keywords = set()
    for line in text.split('\n')[:50]:
        for m in re.finditer(r'\b([A-Z][A-Z0-9_]{2,})\b', line):
            keywords.add(m.group(1))
    
    return {
        "task_id": task_id,
        "files": files[:3],
        "symbol_samples": symbol_samples[:5],
        "keyword_samples": keyword_samples[:5],
        "representative_samples": representative_samples,
        "total_add_lines": len(all_add_lines),
        "keywords": sorted(keywords)[:10],
    }


def main():
    if len(sys.argv) < 4:
        print("用法: detect_duplicate_sample.py <patch-dir> <repo-path> <output-json>", file=sys.stderr)
        sys.exit(2)
    
    patch_dir = Path(sys.argv[1])
    repo_path = Path(sys.argv[2])
    output_json = Path(sys.argv[3])
    
    if not patch_dir.is_dir():
        print(f"错误: patch 目录不存在: {patch_dir}", file=sys.stderr)
        sys.exit(2)
    
    if not repo_path.is_dir():
        print(f"错误: 仓库路径不存在: {repo_path}", file=sys.stderr)
        sys.exit(2)
    
    print("=" * 60)
    print("  抽样检测：提取关键代码行")
    print("=" * 60)
    print(f"  Patch 目录: {patch_dir}")
    print(f"  目标仓库:   {repo_path}")
    print("=" * 60)
    
    results = []
    grep_commands = []
    
    patches = sorted(patch_dir.glob('0*.patch'))
    
    for patch in patches:
        info = extract_samples(patch)
        results.append(info)
        
        task_id = info["task_id"]
        print(f"\n[{task_id}] 解析完成:")
        print(f"  涉改文件: {len(info['files'])} 个")
        print(f"  符号样本: {len(info['symbol_samples'])} 个")
        print(f"  关键词样本: {len(info['keyword_samples'])} 个")
        print(f"  总新增行: {info['total_add_lines']} 行")
        print(f"  关键词: {', '.join(info['keywords'][:5])}")
        
        # 输出 grep 命令（供 Bash 执行）
        for file in info["files"]:
            target_file = repo_path / file
            if target_file.exists():
                # 符号样本（优先）
                for sample in info["symbol_samples"][:2]:
                    sample_clean = sample.replace('"', '').replace("'", '').replace('$', '')
                    grep_commands.append(f"{task_id}|{file}|{sample_clean[:80]}")
                
                # 关键词样本（补充）
                for sample in info["keyword_samples"][:1]:
                    sample_clean = sample.replace('"', '').replace("'", '').replace('$', '')
                    grep_commands.append(f"{task_id}|{file}|{sample_clean[:80]}")
    
    # 输出摘要 JSON（供 AI 分析）
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, 'w') as f:
        json.dump({
            "patches": results,
            "total_patches": len(results),
            "scan_mode": "sampling",
        }, f, indent=2)
    
    print(f"\n✅ 已生成: {output_json}")
    print(f"✅ 抽样命令数: {len(grep_commands)}")
    
    # 输出 grep 命令（stdout，供 Bash 读取）
    for cmd in grep_commands:
        print(cmd)


if __name__ == "__main__":
    main()