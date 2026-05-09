"""接口变化检查和交互确认模块

负责深度思考接口变化影响并与用户交互确认
"""
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List
from .interface_detector import InterfaceChange, find_callers_in_repo


@dataclass
class AdaptationPlan:
    """接口适配方案"""
    interface_change: InterfaceChange
    callers: List
    suggested_modifications: List[str]


def deep_think_interface_adaptation(
    repo_path: Path,
    patch_info: 'PatchInfo',
    interface_changes: List[InterfaceChange]
) -> List[AdaptationPlan]:
    """深度思考接口变化的影响和适配方案

    分析每个接口变化：
    1. 找出所有调用该接口的代码位置
    2. 思考如何根据当前改动修改调用代码
    3. 生成修改建议
    """
    plans = []

    for change in interface_changes:
        callers = find_callers_in_repo(repo_path, change.function_name)

        suggested = []
        if change.old_signature == "<新增函数>":
            suggested.append(f"新函数 {change.function_name} 已添加，无需修改现有调用")
        else:
            for caller in callers:
                # 简单分析：检查是否需要添加参数
                if len(change.new_signature.split('(')[1].split(')')[0].split(',')) > \
                   len(change.old_signature.split('(')[1].split(')')[0].split(',')):
                    # 新增了参数
                    suggested.append(
                        f"  - {caller.file}:{caller.line} - "
                        f"调用 {change.function_name} 时需要补充新参数"
                    )
                else:
                    suggested.append(
                        f"  - {caller.file}:{caller.line} - "
                        f"检查调用 {change.function_name} 是否受影响"
                    )

        if not callers:
            suggested.append("  (未找到调用方，可能是新增接口或内部使用)")

        plans.append(AdaptationPlan(
            interface_change=change,
            callers=callers,
            suggested_modifications=suggested
        ))

    return plans


def format_interface_change_report(
    patch_info: 'PatchInfo',
    plans: List[AdaptationPlan]
) -> str:
    """格式化接口变化报告"""
    lines = [
        f"╔{'═'*60}╗",
        f"║{'Patch ' + str(patch_info.index) + ' - 接口变化检测报告':^60}║",
        f"╚{'═'*60}╝",
        "",
        f"【{patch_info.subject}】",
        "",
        f"检测到 {len(plans)} 处接口变化：",
        ""
    ]

    for i, plan in enumerate(plans, 1):
        change = plan.interface_change
        lines.append(f"--- 变化 {i} ---")
        lines.append(f"  文件: {change.file_path}")
        lines.append(f"  函数: {change.function_name}")
        lines.append(f"  旧签名: {change.old_signature}")
        lines.append(f"  新签名: {change.new_signature}")

        if plan.callers:
            lines.append("")
            lines.append(f"  影响的调用方 ({len(plan.callers)} 处)：")
            for caller in plan.callers:
                lines.append(f"    - {caller.file}:{caller.line}")
                lines.append(f"      当前调用: {caller.current_call[:50]}...")

        lines.append("")
        lines.append("  建议修改方案：")
        if plan.suggested_modifications:
            for mod in plan.suggested_modifications:
                lines.append(f"    {mod}")
        else:
            lines.append("    (无)")

        lines.append("")

    lines.append(f"{'─'*60}")
    lines.append("请选择如何处理：")
    lines.append("")
    lines.append("  1. 手动处理后继续（推荐）")
    lines.append("  2. 停止整个流程")
    lines.append("")
    lines.append("输入选项编号 (1-2)，或输入 'm' 手动处理后输入任意键继续：")

    return "\n".join(lines)


def deep_think_and_confirm(
    repo_path: Path,
    patch_info: 'PatchInfo',
    interface_changes: List[InterfaceChange]
) -> str:
    """深度思考 + 交互确认

    1. 分析接口变化影响
    2. 呈现报告给用户
    3. 等待用户确认

    Returns:
        'continue' - 用户确认后继续
        'stop' - 用户要求停止
    """
    plans = deep_think_interface_adaptation(repo_path, patch_info, interface_changes)
    report = format_interface_change_report(patch_info, plans)

    print(f"\n{report}")

    while True:
        choice = input("请输入选项：").strip()

        if choice == '1':
            print("\n请手动处理接口适配问题...")
            print("处理完成后，输入任意内容继续（输入 's' 停止流程）：")
            user_input = input("> ").strip()
            if user_input.lower() == 's':
                return 'stop'
            return 'continue'
        elif choice == '2':
            return 'stop'
        elif choice.lower() == 'm':
            print("\n请手动处理接口适配问题...")
            print("处理完成后，输入任意内容继续（输入 's' 停止流程）：")
            user_input = input("> ").strip()
            if user_input.lower() == 's':
                return 'stop'
            return 'continue'
        else:
            print("无效选项，请重新输入：")


def prompt_user_on_compile_failure(compilation: 'CompilationResult') -> str:
    """编译失败时询问用户

    Returns:
        'continue' - 用户确认后继续
        'stop' - 用户要求停止
    """
    print(f"\n{'='*60}")
    print(f"编译失败")
    print(f"{'='*60}")
    print("请选择如何处理：")
    print("")
    print("  1. 停止整个流程（推荐）")
    print("  2. 继续，但后续 patch 不再自动编译")
    print("")
    print("输入选项编号 (1-2)：")

    while True:
        choice = input("请输入选项：").strip()
        if choice == '1':
            return 'stop'
        elif choice == '2':
            return 'continue'
        else:
            print("无效选项，请重新输入：")