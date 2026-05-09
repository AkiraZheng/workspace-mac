"""接口变化检测模块

负责检测 patch 合入后的函数/方法签名变化
"""
import re
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class InterfaceChange:
    """接口变化"""
    file_path: str
    function_name: str
    old_signature: str
    new_signature: str


@dataclass
class CallerInfo:
    """调用方信息"""
    file: str
    line: int
    current_call: str
    suggested_fix: str


def is_interface_file(file_path: str) -> bool:
    """判断是否为接口文件（包含函数定义的文件）"""
    interface_extensions = {'.h', '.c', '.cpp', '.hpp', '.go', '.rs', '.py', '.java'}
    return any(file_path.endswith(ext) for ext in interface_extensions)


def extract_function_signatures(content: str) -> Dict[str, str]:
    """提取文件中的函数签名

    Returns:
        {函数名: 完整签名}
    """
    signatures = {}

    # C/C++ 函数签名正则
    # 匹配: 返回类型 函数名(参数)
    c_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_*\s]+?)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)'
    for match in re.finditer(c_pattern, content):
        return_type = match.group(1).strip()
        func_name = match.group(2).strip()
        params = match.group(3).strip()
        signatures[func_name] = f"{return_type} {func_name}({params})"

    # Python 函数签名正则
    py_pattern = r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\):'
    for match in re.finditer(py_pattern, content, re.MULTILINE):
        func_name = match.group(1)
        params = match.group(2)
        signatures[func_name] = f"def {func_name}({params}):"

    return signatures


def get_file_at_commit(repo_path: Path, commit_hash: str, file_path: str) -> Optional[str]:
    """获取指定 commit 时文件的内容"""
    try:
        result = subprocess.run(
            ['git', 'show', f'{commit_hash}:{file_path}'],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None


def detect_interface_changes(
    repo_path: Path,
    patch_info: 'PatchInfo',
    old_commit_hash: str
) -> List[InterfaceChange]:
    """检测接口变化

    对比 patch 合入前后的函数签名变化

    Args:
        repo_path: 仓库路径
        patch_info: patch 信息
        old_commit_hash: patch 合入前的 commit hash

    Returns:
        接口变化列表
    """
    changes = []

    for file_path in patch_info.files_changed:
        if not is_interface_file(file_path):
            continue

        # 获取旧版本
        old_content = get_file_at_commit(repo_path, old_commit_hash, file_path)
        if old_content is None:
            # 文件是新增的，跳过
            continue

        # 获取新版本
        file_full_path = repo_path / file_path
        if not file_full_path.exists():
            continue
        new_content = file_full_path.read_text()

        # 提取签名
        old_sigs = extract_function_signatures(old_content)
        new_sigs = extract_function_signatures(new_content)

        # 对比差异
        for func_name, new_sig in new_sigs.items():
            if func_name in old_sigs:
                if old_sigs[func_name] != new_sig:
                    changes.append(InterfaceChange(
                        file_path=file_path,
                        function_name=func_name,
                        old_signature=old_sigs[func_name],
                        new_signature=new_sig
                    ))
            else:
                # 新增的函数
                changes.append(InterfaceChange(
                    file_path=file_path,
                    function_name=func_name,
                    old_signature="<新增函数>",
                    new_signature=new_sig
                ))

    return changes


def find_callers_in_repo(repo_path: Path, function_name: str) -> List[CallerInfo]:
    """在仓库中查找调用指定函数的位置"""
    callers = []

    # 使用 grep 搜索函数调用
    result = subprocess.run(
        ['grep', '-rn', '--include=*.c', '--include=*.cpp', '--include=*.h',
         '--include=*.py', function_name, str(repo_path)],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split(':', 2)
            if len(parts) < 3:
                continue

            file_path = parts[0]
            line_num = parts[1]
            call_content = parts[2].strip()

            # 排除函数定义行
            if f'def {function_name}' in call_content or f'{function_name}(' not in call_content:
                continue

            callers.append(CallerInfo(
                file=file_path,
                line=int(line_num),
                current_call=call_content,
                suggested_fix=f"<需要修改以适配新签名>"
            ))

    return callers