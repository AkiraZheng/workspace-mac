#!/bin/bash
# detect_build_target.sh — 根据涉改文件动态选择编译目标
#
# 输入:
#   --files "file1.c file2.h ..."     涉改文件列表
#   --merges-file <path> --task-id <id>  从 merge_tasks.json 读取
#   --repo-path <path>                内核仓库路径（检查 .config）
#
# 输出 (stdout):
#   Image          仅编译内核镜像
#   Image modules  编译镜像 + 模块
#
# 退出码: 0=成功, 1=参数错误
set -euo pipefail

FILES=""
REPO_PATH=""
MERGE_FILE=""
TASK_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --files)
            FILES="$2"; shift 2 ;;
        --repo-path)
            REPO_PATH="$2"; shift 2 ;;
        --merges-file)
            MERGE_FILE="$2"; shift 2 ;;
        --task-id)
            TASK_ID="$2"; shift 2 ;;
        *)
            echo "未知参数: $1" >&2; exit 1 ;;
    esac
done

# 从 merge_tasks.json 提取 files_changed
if [ -n "$MERGE_FILE" ] && [ -n "$TASK_ID" ]; then
    if [ ! -f "$MERGE_FILE" ]; then
        echo "merge_tasks.json 不存在: $MERGE_FILE" >&2
        exit 1
    fi
    FILES=$(python3 -c "
import json, sys
d = json.load(open('$MERGE_FILE'))
for section in ['deps_order', 'merge_order']:
    for t in d.get(section, []):
        if t.get('task_id') == '$TASK_ID':
            for f in t.get('files_changed', []):
                print(f)
            sys.exit(0)
" 2>/dev/null)
fi

if [ -z "$FILES" ]; then
    echo "错误: 未提供涉改文件列表" >&2
    echo "用法: $0 --files 'drivers/gpu/file.c' 或 --merges-file ... --task-id ..." >&2
    exit 1
fi

HAS_DRIVER=0
DRIVER_DIRS=""

# 模块支持代码 → 始终需要 make modules
if echo "$FILES" | grep -q "arch/.*/kernel/module"; then
    echo "Image modules"
    exit 0
fi

for f in $FILES; do
    case "$f" in
        drivers/*|sound/*)
            HAS_DRIVER=1
            DRIVER_DIRS="$DRIVER_DIRS $f"
            ;;
    esac
done

if [ "$HAS_DRIVER" -eq 0 ]; then
    echo "Image"
    exit 0
fi

# 有驱动文件 → 无 .config 则保守：也需要 modules
if [ -z "$REPO_PATH" ] || [ ! -f "$REPO_PATH/.config" ]; then
    echo "Image modules"
    exit 0
fi

# ── 解析 Makefile obj-$(CONFIG_XXX) + 查 .config ──
HAS_MODULE_CONFIG=0

for f in $DRIVER_DIRS; do
    dir_path=$(dirname "$f")
    makefile="${REPO_PATH}/${dir_path}/Makefile"

    if [ ! -f "$makefile" ]; then
        # 所在目录无 Makefile → 保守：需要 modules
        HAS_MODULE_CONFIG=1
        break
    fi

    # 提取 Makefile 中所有 obj-$(CONFIG_XXX) 的 CONFIG 名
    configs=$(grep -oP 'obj-\$\((\w+)\)' "$makefile" 2>/dev/null \
        | sed 's/obj-\$(\(.*\))/\1/' | sort -u || true)

    if [ -z "$configs" ]; then
        # Makefile 没有 obj-$(CONFIG_XXX) → 保守：需要 modules
        HAS_MODULE_CONFIG=1
        break
    fi

    # 查 .config 是否有任一 CONFIG=m
    for cfg in $configs; do
        if grep -q "^${cfg}=m$" "$REPO_PATH/.config" 2>/dev/null; then
            HAS_MODULE_CONFIG=1
            break 2
        fi
    done
done

if [ "$HAS_MODULE_CONFIG" -eq 1 ]; then
    echo "Image modules"
else
    echo "Image"
fi
