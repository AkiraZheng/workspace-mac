"""Claude Code Skill 入口

【核心约束 - 必须遵守】
1. 源 patchset 有多少个 patch，就必须逐个合入
2. 每个 patch 必须单独 git commit
3. 遇到问题必须解决（冲突、版本不匹配等），不能跳过
4. 保留分支，不删除
5. 所有思考和输出必须使用中文
"""

import subprocess
import re
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List
from .b4_installer import ensure_b4
from .patchset_downloader import download_patchset
from .diff_tracker import DiffTracker, DiffEntry
from .interface_detector import detect_interface_changes, InterfaceChange


def prompt_user_on_compile_failure() -> int:
    """询问用户编译失败时的处理方式

    Returns:
        1: 跳过继续下一个 patch
        2: 停止整个合入流程
    """
    print("\n请选择处理方式：")
    print("  1. 跳过继续（不推荐，可能导致后续 patch 也有问题）")
    print("  2. 停止整个合入流程")
    while True:
        try:
            choice = int(input("输入选项编号 (1-2): ").strip())
            if choice in [1, 2]:
                return choice
            print("请输入 1 或 2")
        except ValueError:
            print("请输入有效的数字")


def deep_think_and_confirm(interface_changes: List[InterfaceChange]) -> bool:
    """对接口变化进行深度思考并确认

    Args:
        interface_changes: 检测到的接口变化列表

    Returns:
        True: 用户确认可以继续
        False: 用户选择停止
    """
    print("\n接口变化确认：")
    print("  1. 确认接口变化，继续合入")
    print("  2. 停止合入流程")
    while True:
        try:
            choice = int(input("输入选项编号 (1-2): ").strip())
            if choice == 1:
                return True
            elif choice == 2:
                return False
            print("请输入 1 或 2")
        except ValueError:
            print("请输入有效的数字")


class PatchApplyFailed(Exception):
    """Patch 合入失败异常

    当 patch 合入失败时抛出，携带详细信息供用户决策
    """
    def __init__(
        self,
        patch_info: 'PatchInfo',
        attempted_strategies: List[str],
        last_error: str,
        conflict_files: List[str] = None,
        suggested_resolutions: List[str] = None
    ):
        self.patch_info = patch_info
        self.attempted_strategies = attempted_strategies
        self.last_error = last_error
        self.conflict_files = conflict_files or []
        self.suggested_resolutions = suggested_resolutions or []

        conflict_files_str = "\n".join(f"  - {f}" for f in self.conflict_files) if self.conflict_files else "  无冲突标记"
        suggestions_str = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(self.suggested_resolutions)) if self.suggested_resolutions else ""

        message = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                           Patch 合入失败                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

【Patch {patch_info.index}】 {patch_info.subject}

【已尝试的策略】
{chr(10).join(f"  {i+1}. {s}" for i, s in enumerate(attempted_strategies))}

【错误信息】
{last_error[:300]}

【冲突文件】
{conflict_files_str}
"""
        if suggestions_str:
            message += f"""
【建议解决方案】
{suggestions_str}
"""

        message += f"""
═══════════════════════════════════════════════════════════════════════════════════

请选择如何处理：

  1. 跳过此 patch，继续下一个（不推荐，patch 有依赖）
  2. 停止整个合入流程

输入选项编号 (1-2)。
"""
        super().__init__(message)

@dataclass
class PatchInfo:
    """单个 Patch 信息"""
    index: int
    subject: str
    patch_content: str
    files_changed: List[str]
    success: bool = False
    commit_hash: str = ""
    error_message: str = ""

@dataclass
class PatchsetMergeResult:
    """Patchset 合入结果"""
    total_patches: int
    successful_patches: int
    failed_patches: int
    patch_results: List[PatchInfo]
    branch_name: str

@dataclass
class CompilationResult:
    """编译结果"""
    success: bool
    output: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

def split_mbox_to_patches(mbox_path: Path) -> List[PatchInfo]:
    """拆分 mbox 文件为单个 patch"""
    content = mbox_path.read_text()

    # 使用 From 行拆分 patch
    pattern = r'(^From \S+@\S+ .*?)(?=\nFrom \S+@\S+|\Z)'
    matches = list(re.finditer(pattern, content, re.MULTILINE | re.DOTALL))

    patches = []
    for i, match in enumerate(matches):
        patch_text = match.group(1).strip()
        if not patch_text:
            continue

        subject_match = re.search(r'^Subject:\s*(.+)$', patch_text, re.MULTILINE)
        subject = subject_match.group(1).strip() if subject_match else f"Patch {i+1}"

        files = re.findall(r'^\+\+\+ b/(.+)$', patch_text, re.MULTILINE)
        files = [f for f in files if f]

        patches.append(PatchInfo(
            index=i + 1,
            subject=subject,
            patch_content=patch_text,
            files_changed=files,
            success=False
        ))

    return patches

def has_conflict_markers(repo_path: Path) -> bool:
    """检测是否有冲突标记"""
    result = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=U'],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    conflict_files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
    return len(conflict_files) > 0

def try_git_am(repo_path: Path, patch_file: Path) -> tuple[bool, str]:
    """尝试 git am 合入（不自动 commit）

    Returns:
        (success, output_message)
    """
    result = subprocess.run(
        ['git', 'am', str(patch_file)],
        cwd=repo_path,
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        # am 成功，staged 状态，不 commit
        return True, "git am 成功"
    else:
        return False, result.stderr

def try_git_apply(repo_path: Path, patch_file: Path) -> tuple[bool, str]:
    """尝试 git apply --3way 合入

    Returns:
        (success, commit_hash_or_error_message)
    """
    # 先 stash 当前更改
    subprocess.run(['git', 'stash', '-k', '--include-untracked'], cwd=repo_path, capture_output=True)

    result = subprocess.run(
        ['git', 'apply', '--3way', str(patch_file)],
        cwd=repo_path,
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        # 有冲突，但 apply 成功了部分
        # 检查是否有未合并的变更
        status_result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if status_result.stdout.strip():
            # 有未合并的变更，需要解决
            return False, "git apply --3way 有未合并的变更"
        else:
            # 完全成功，add 但不 commit
            subprocess.run(['git', 'add', '.'], cwd=repo_path, capture_output=True)
            return True, "apply_success"
    else:
        return False, result.stderr

def try_manual_apply_and_commit(
    repo_path: Path,
    patch_info: PatchInfo,
    diff_tracker: DiffTracker
) -> tuple[bool, str]:
    """尝试手动 apply（不 commit）

    适用于版本不匹配的情况，尝试用 git apply
    然后手动 add 但不 commit

    Returns:
        (success, message)
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
        f.write(patch_info.patch_content)
        patch_file = Path(f.name)

    try:
        # 尝试普通 git apply
        result = subprocess.run(
            ['git', 'apply', str(patch_file)],
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            # apply 成功，add 但不 commit
            subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True)
            return True, "手动 apply 成功"
        else:
            # apply 失败，记录差异报告供 AI 后续处理
            diff_tracker.add_entry(
                file_path=f"[Patch {patch_info.index}] {patch_info.subject}",
                original=patch_info.patch_content[:1000],
                applied=f"<无法应用>\n{result.stderr[:500]}",
                reason="patch_cannot_apply",
                patch_hash=""
            )
            return False, f"git apply 失败: {result.stderr[:200]}"

    finally:
        patch_file.unlink(missing_ok=True)

def resolve_conflicts_and_commit(
    repo_path: Path,
    patch_info: PatchInfo,
    diff_tracker: DiffTracker
) -> tuple[bool, str, List[str]]:
    """尝试找方法解冲突

    检测到冲突后分析冲突内容，思考可能的解决方案，返回给调用者。

    Returns:
        (success, commit_hash_or_error_message, suggested_resolutions)
    """
    conflict_files = []
    result = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=U'],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    conflict_files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]

    if not conflict_files:
        return False, "没有检测到冲突文件", []

    print(f"  检测到 {len(conflict_files)} 个冲突文件，尝试找方法解冲突...")

    # 获取冲突文件的冲突内容详情
    conflict_details = []
    for cf in conflict_files:
        file_path = repo_path / cf
        if not file_path.exists():
            continue

        content = file_path.read_text()
        if '<<<<<<<' not in content:
            continue

        conflict_details.append(f"\n=== {cf} ===\n{content}")

    full_error = f"检测到 {len(conflict_files)} 个冲突文件，需要思考如何解决:\n" + "\n".join(conflict_details)

    # 记录到 diff_tracker
    diff_tracker.add_entry(
        file_path=f"[Patch {patch_info.index}] {patch_info.subject}",
        original="<冲突>",
        applied=full_error[:2000],
        reason="conflict_detected",
        patch_hash=""
    )

    # 分析冲突，给出建议
    # 这里只是简单分析，实际应该更智能地分析
    suggestions = []
    if len(conflict_files) == 1:
        suggestions.append("查看冲突文件，手动合并两边的修改")
        suggestions.append("根据代码语义决定保留哪边的修改")
    else:
        suggestions.append("逐个文件分析冲突，根据业务逻辑决定保留内容")
        suggestions.append("注意多个文件间可能有相互依赖的修改")

    return False, full_error, suggestions

def apply_single_patch_with_retry(
    repo_path: Path,
    patch_info: PatchInfo,
    diff_tracker: DiffTracker
) -> PatchInfo:
    """尝试合入单个 patch，使用多种策略

    策略顺序：
    1. git am
    2. 如果失败且有冲突 → 解冲突 → commit
    3. 如果失败且无冲突 → 尝试 git apply
    4. 如果还失败 → 抛出 PatchApplyFailed 异常询问用户

    Returns:
        PatchInfo with updated success/commit_hash/error_message

    Raises:
        PatchApplyFailed: 当所有策略都失败时抛出，携带详细信息供用户决策
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
        f.write(patch_info.patch_content)
        patch_file = Path(f.name)

    attempted_strategies = []
    conflict_files = []

    try:
        print(f"[{patch_info.index}] 正在合入: {patch_info.subject}")

        # 策略1: git am
        attempted_strategies.append("git am")
        success, result = try_git_am(repo_path, patch_file)

        if success:
            patch_info.success = True
            patch_info.commit_hash = result
            print(f"  ✓ git am 成功: {result[:12]}")
            return patch_info

        # git am 失败，检测是否有冲突
        if has_conflict_markers(repo_path):
            # 获取冲突文件列表
            result_detect = subprocess.run(
                ['git', 'diff', '--name-only', '--diff-filter=U'],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            conflict_files = [f.strip() for f in result_detect.stdout.strip().split('\n') if f.strip()]

            # 策略2: 解冲突
            attempted_strategies.append("解冲突 (思考解决方案)")
            print(f"  ⚠ git am 失败，有冲突，尝试找方法解冲突...")
            success, result, suggestions = resolve_conflicts_and_commit(repo_path, patch_info, diff_tracker)

            if success:
                patch_info.success = True
                patch_info.commit_hash = result
                print(f"  ✓ 解冲突成功: {result[:12]}")
                return patch_info
            else:
                # 解冲突失败，抛出异常询问用户
                print(f"  ✗ 解冲突失败，思考解决方案...")
                raise PatchApplyFailed(
                    patch_info=patch_info,
                    attempted_strategies=attempted_strategies,
                    last_error=f"解冲突失败，需要人工判断:\n{result[:500]}",
                    conflict_files=conflict_files,
                    suggested_resolutions=suggestions
                )
        else:
            # 没有冲突标记，可能是版本不匹配等问题
            # 策略3: 尝试 git apply
            attempted_strategies.append("git apply --3way")
            print(f"  ⚠ git am 失败，无冲突标记，尝试 git apply...")
            success, result = try_git_apply(repo_path, patch_file)

            if success:
                # add 但不 commit
                subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True)
                patch_info.success = True
                patch_info.commit_hash = ""
                print(f"  ✓ git apply 成功")
                return patch_info
            else:
                # 策略4: 尝试普通 git apply + commit
                attempted_strategies.append("git apply (手动)")
                print(f"  ⚠ git apply 失败，尝试手动 apply...")
                success, result = try_manual_apply_and_commit(repo_path, patch_info, diff_tracker)

                if success:
                    patch_info.success = True
                    patch_info.commit_hash = result
                    print(f"  ✓ 手动 apply 成功: {result[:12]}")
                    return patch_info
                else:
                    # 所有策略都失败，抛出异常询问用户
                    print(f"  ✗ 所有策略都失败")
                    raise PatchApplyFailed(
                        patch_info=patch_info,
                        attempted_strategies=attempted_strategies,
                        last_error=result,
                        conflict_files=conflict_files,
                        suggested_resolutions=["请思考如何解决这个合入问题"]
                    )

    finally:
        patch_file.unlink(missing_ok=True)

def apply_patchset_one_by_one(
    repo_path: Path,
    patches: List[PatchInfo],
    diff_tracker: DiffTracker
) -> PatchsetMergeResult:
    """逐个合入 patchset

    【核心原则】
    - 必须按顺序逐个 patch 合入
    - 每个 patch 必须单独 commit
    - 遇到问题必须尝试解决
    - 如果当前 patch 合入失败，停止整个流程，不能跳到下一个 patch
    """
    successful = 0
    failed = 0
    results = []

    print(f"\n{'='*60}")
    print(f"开始逐个合入 Patchset（共 {len(patches)} 个 patch）")
    print(f"{'='*60}\n")

    for i, patch in enumerate(patches):
        # 记录合入前的 commit hash（用于后续接口变化检测）
        old_commit_hash = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True
        ).stdout.strip()

        patch = apply_single_patch_with_retry(repo_path, patch, diff_tracker)
        results.append(patch)

        if patch.success:
            successful += 1
            print(f"  ✓ 合入成功")

            # 接口变化检测（BEFORE commit）
            from .interface_detector import detect_interface_changes
            interface_changes = detect_interface_changes(repo_path, patch, old_commit_hash)

            if interface_changes:
                print(f"\n{'='*60}")
                print(f"【接口变化检测】发现 {len(interface_changes)} 处接口变化")
                print(f"{'='*60}")
                for change in interface_changes:
                    print(f"\n  文件: {change.file_path}")
                    print(f"  函数: {change.function_name}")
                    print(f"  旧签名: {change.old_signature}")
                    print(f"  新签名: {change.new_signature}")

                    # 记录接口变化到 diff_tracker
                    diff_tracker.add_entry(
                        file_path=f"[Patch {patch.index}] {change.file_path}",
                        original=change.old_signature,
                        applied=change.new_signature,
                        reason=f"interface_changed: {change.function_name}",
                        patch_hash=patch.commit_hash
                    )

                # 用户交互确认
                from .interface_checker import deep_think_and_confirm
                decision = deep_think_and_confirm(repo_path, patch, interface_changes)
                if decision == 'stop':
                    # 用户选择停止
                    for remaining_patch in patches[i+1:]:
                        remaining_patch.success = False
                        remaining_patch.error_message = "因接口变化未确认停止"
                        results.append(remaining_patch)
                        failed += 1
                    break

            # 用户确认后 COMMIT
            subprocess.run(['git', 'add', '.'], cwd=repo_path, capture_output=True)
            commit_msg = f"""{patch.subject}

[Patch-index: {patch.index}]
"""
            subprocess.run(
                ['git', 'commit', '-m', commit_msg],
                cwd=repo_path,
                capture_output=True
            )
            patch.commit_hash = subprocess.run(
                ['git', 'log', '-1', '--format=%H'],
                cwd=repo_path,
                capture_output=True,
                text=True
            ).stdout.strip()
            print(f"  ✓ 已提交: {patch.commit_hash[:12]}")

            # THEN 编译验证
            compile_result = compile_project(repo_path)
            if not compile_result.success:
                # 编译失败，询问用户
                print(f"\n{'='*60}")
                print(f"【编译失败】Patch {patch.index} 合入后编译失败")
                print(f"{'='*60}")
                if compile_result.errors:
                    print("\n错误信息：")
                    for err in compile_result.errors[:10]:
                        print(f"  {err}")

                user_choice = prompt_user_on_compile_failure()
                if user_choice == 2:
                    # 用户选择停止
                    failed += 1
                    for remaining_patch in patches[i+1:]:
                        remaining_patch.success = False
                        remaining_patch.error_message = "因编译失败停止"
                        results.append(remaining_patch)
                        failed += 1
                    break
                # 用户选择继续（user_choice == 1）

            # 记录编译结果到 diff_tracker
            add_compilation_diff_entries(diff_tracker, compile_result)

            print(f"  ✓ 编译验证通过，继续下一个")
        else:
            failed += 1
            # 记录失败的 patch
            diff_tracker.add_entry(
                file_path=f"[Patch {patch.index}] {patch.subject}",
                original=patch.patch_content[:500],
                applied=f"<合入失败>\n{patch.error_message[:200] if patch.error_message else 'unknown'}",
                reason="patch_failed",
                patch_hash=""
            )

            # 【关键】Patch 合入失败，停止整个流程，不能跳到下一个
            print(f"\n{'='*60}")
            print(f"【停止】Patch {patch.index} 合入失败，停止后续 patch 合入")
            print(f"{'='*60}")

            # 更新剩余 patch 的状态为"未尝试"
            for remaining_patch in patches[i+1:]:
                remaining_patch.success = False
                remaining_patch.error_message = "因前面 patch 合入失败而未尝试"
                results.append(remaining_patch)
                failed += 1

            break

    return PatchsetMergeResult(
        total_patches=len(patches),
        successful_patches=successful,
        failed_patches=failed,
        patch_results=results,
        branch_name=""
    )

def compile_project(repo_path: Path) -> CompilationResult:
    """编译项目"""
    print(f"\n开始编译验证...")

    build_script = repo_path / "build.sh"
    if build_script.exists():
        result = subprocess.run(
            ["bash", str(build_script)],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=3600
        )
    else:
        result = subprocess.run(
            ["make", "-j$(nproc)"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=3600
        )

    output = result.stdout + result.stderr

    errors = []
    warnings = []

    for line in output.split('\n'):
        line_lower = line.lower()
        if 'error:' in line_lower or '错误' in line:
            errors.append(line.strip())
        elif 'warning:' in line_lower or '警告' in line:
            warnings.append(line.strip())

    return CompilationResult(
        success=(result.returncode == 0),
        output=output[-5000:] if len(output) > 5000 else output,
        errors=errors,
        warnings=warnings
    )

def add_compilation_diff_entries(
    diff_tracker: DiffTracker,
    compilation_result: CompilationResult
):
    """将编译结果记录到差异报告"""
    if compilation_result.success and not compilation_result.errors:
        diff_tracker.add_entry(
            file_path="[编译验证]",
            original="编译成功",
            applied="✓ 编译通过，无错误和警告",
            reason="compilation_success"
        )
        return

    if compilation_result.errors:
        error_summary = "\n".join(compilation_result.errors[:20])
        diff_tracker.add_entry(
            file_path="[编译错误]",
            original="<编译错误>",
            applied=f"<编译错误>\n{error_summary}",
            reason="compilation_error"
        )

    if compilation_result.warnings:
        warning_summary = "\n".join(compilation_result.warnings[:10])
        diff_tracker.add_entry(
            file_path="[编译警告]",
            original="<编译警告>",
            applied=f"<编译警告>\n{warning_summary}",
            reason="compilation_warning"
        )

def execute_patchset_merge(patch_url: str, source_repo: Path, branch_name: str) -> PatchsetMergeResult:
    """执行 patchset merge 工作流

    【核心原则 - 必须遵守】
    1. 逐个合入：源 patchset 有多少个 patch，就必须逐个合入
    2. 逐个 commit：每个成功的 patch 必须单独 commit
    3. 解决问题：遇到冲突、版本不匹配等问题必须解决，不能跳过
    4. 保留分支：合入结果分支必须保留，不删除
    5. 中文输出：所有思考、解释、输出必须使用中文
    """
    if not ensure_b4():
        raise RuntimeError("Failed to install b4")

    temp_dir = Path("/tmp/patchset-merge")
    temp_dir.mkdir(exist_ok=True)

    mbox_path, mbox_hash = download_patchset(patch_url, temp_dir)
    print(f"已下载 patchset: {mbox_hash[:16]}...")

    # 拆分 patchset 为单个 patch
    patches = split_mbox_to_patches(mbox_path)
    print(f"发现 {len(patches)} 个 patch，准备逐个合入...")

    # 根据 patch 主题生成分支名
    if patches:
        first_subject = patches[0].subject
        keywords = re.sub(r'^\[.*?\]\s*', '', first_subject)
        keywords = re.sub(r'\s+', '-', keywords)[:40]
        keywords = re.sub(r'[^a-zA-Z0-9\-]', '', keywords)
        if keywords:
            auto_branch_name = f"patch-{keywords}"
        else:
            auto_branch_name = None
    else:
        auto_branch_name = None

    # 如果用户没有指定分支名，或者指定了但为空，使用自动生成的
    if not branch_name:
        branch_name = auto_branch_name

    # 如果自动生成分支名也为空，生成一个基于时间的唯一名称
    if not branch_name:
        import time
        branch_name = f"patch-{int(time.time())}"

    print(f"\n将使用分支: {branch_name}")

    # 检查分支是否存在，如果存在则生成新的唯一名称
    base_branch_name = branch_name
    counter = 1
    while True:
        result = subprocess.run(
            ['git', 'rev-parse', '--verify', f'refs/heads/{branch_name}'],
            cwd=source_repo,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # 分支不存在，可以创建
            break

        # 分支已存在，生成新的名称
        import time
        branch_name = f"{base_branch_name}-{int(time.time())}"
        counter += 1
        if counter > 10:
            # 防止无限循环
            branch_name = f"{base_branch_name}-retry-{int(time.time())}"
            break

    print(f"\n创建新分支: {branch_name}")
    subprocess.run(
        ['git', 'checkout', '-b', branch_name],
        cwd=source_repo,
        check=True
    )
    print(f"✓ 分支创建成功")

    diff_tracker = DiffTracker(source_repo)

    # 逐个合入 patch
    merge_result = apply_patchset_one_by_one(source_repo, patches, diff_tracker)
    merge_result.branch_name = branch_name

    # 编译验证
    print(f"\n{'='*60}")
    print(f"开始编译验证")
    print(f"{'='*60}")
    compilation = compile_project(source_repo)
    add_compilation_diff_entries(diff_tracker, compilation)

    if compilation.success:
        print(f"✓ 编译通过！")
    else:
        print(f"⚠ 编译存在问题，已记录到差异报告")

    # 生成差异报告
    diff_report_path = source_repo / ".patchset-diff.md"
    diff_tracker.save_diff_report(diff_report_path)

    # 输出总结
    print(f"\n{'='*60}")
    print(f"Patchset 合入完成")
    print(f"{'='*60}")
    print(f"分支: {branch_name} （已保留）")
    print(f"总数: {merge_result.total_patches}")
    print(f"成功: {merge_result.successful_patches}")
    print(f"失败: {merge_result.failed_patches}")
    print(f"差异报告: {diff_report_path}")

    if merge_result.failed_patches > 0:
        print(f"\n合入失败的 patch（已记录到差异报告）：")
        for p in merge_result.patch_results:
            if not p.success:
                print(f"  - [{p.index}] {p.subject}")
                print(f"    错误: {p.error_message[:80] if p.error_message else 'unknown'}...")

    print(f"\n{'='*60}")
    print(f"【重要】分支 {branch_name} 已保留！")
    print(f"如果需要继续调试失败的 patch，请查看差异报告 {diff_report_path}")
    print(f"{'='*60}")

    return merge_result
