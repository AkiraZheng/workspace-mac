#!/bin/bash
# verify_build.sh — 编译验证门禁
# 检查编译日志 + 最终产物，返回确定性的 pass/fail
#
# 用法:
#   # 手动指定（旧方式兼容）
#   verify_build.sh --log /tmp/patch_build.log \
#     --product arch/arm64/boot/Image \
#     --modules "drivers/gpu/drm"
#
#   # 自动检测模块（推荐，一条命令）
#   verify_build.sh --log /tmp/patch_build_0003.log \
#     --merges-file merge_tasks.json --task-id 0003 \
#     --repo-path "$KERNEL_REPO_PATH" \
#     --product "arch/arm64/boot/Image"
#
# --product:  验证指定文件存在（可多次指定）
# --modules:  验证指定目录下的 .ko 文件存在（手动模式）
# --merges-file + --task-id:  从 merge_tasks.json 读取 files_changed，
#   自动检测是否需要验证模块 .ko（需要 --repo-path 查 .config）
#
# 退出码:
#   0 = 通过
#   1 = 编译日志不存在或为空
#   2 = error 数 > 0
#   3 = 产物缺失（Image 或模块 .ko）
#   4 = 模块目录下无 .ko 文件

set -euo pipefail

BUILD_LOG=""
PRODUCTS=()
MODULE_DIRS=()
NEED_MODULES=0
MERGE_FILE=""
TASK_ID=""
REPO_PATH=""
AUTO_MODULES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --log)
            BUILD_LOG="$2"; shift 2 ;;
        --product)
            PRODUCTS+=("$2"); shift 2 ;;
        --modules)
            NEED_MODULES=1
            for d in $2; do
                MODULE_DIRS+=("$d")
            done
            shift 2 ;;
        --merges-file)
            MERGE_FILE="$2"; shift 2 ;;
        --task-id)
            TASK_ID="$2"; shift 2 ;;
        --repo-path)
            REPO_PATH="$2"; shift 2 ;;
        *) shift ;;
    esac
done

if [ -n "$MERGE_FILE" ] && [ -n "$TASK_ID" ]; then
    if [ ! -f "$MERGE_FILE" ]; then
        echo "[FAIL] merge_tasks.json 不存在: $MERGE_FILE"
        exit 1
    fi

    MERGE_DIR=$(dirname "$MERGE_FILE")
    CONFIG_FILE="${REPO_PATH:+$REPO_PATH/}.config"

    FILES=$(python3 -c "
import json, sys
d = json.load(open('$MERGE_FILE'))
for section in ['deps_order', 'merge_order']:
    for t in d.get(section, []):
        if t.get('task_id') == '$TASK_ID':
            for f in t.get('files_changed', []):
                print(f)
            sys.exit(0)
" 2>/dev/null || true)

    if [ -n "$FILES" ]; then
        NEED_MODULES=0
        for f in $FILES; do
            case "$f" in
                drivers/*|sound/*)
                    mod_dir="${REPO_PATH:+$REPO_PATH/}$(dirname "$f")"
                    if [ -z "$CONFIG_FILE" ] || [ ! -f "$CONFIG_FILE" ]; then
                        NEED_MODULES=1
                        MODULE_DIRS+=("$mod_dir")
                    else
                        while IFS= read -r line; do
                            cfg_name=$(echo "$line" | cut -d= -f1 | sed 's/^CONFIG_//' | tr '[:upper:]' '[:lower:]')
                            if echo "$mod_dir" | grep -qi "$cfg_name"; then
                                NEED_MODULES=1
                                MODULE_DIRS+=("$mod_dir")
                                break
                            fi
                        done < <(grep '=m$' "$CONFIG_FILE" 2>/dev/null || true)
                    fi
                    ;;
            esac
        done
        AUTO_MODULES=$NEED_MODULES
    fi
fi

RC=0

# 1. 编译日志存在且有内容
if [ -z "$BUILD_LOG" ] || [ ! -s "$BUILD_LOG" ]; then
    echo "[FAIL] 编译日志不存在或为空: ${BUILD_LOG:-未指定}"
    RC=1
fi

# 2. error 数 = 0
if [ "$RC" -eq 0 ]; then
    ERR_COUNT=$(grep -c "error:" "$BUILD_LOG" 2>/dev/null || echo 0)
    ERR_COUNT=${ERR_COUNT//[^0-9]/}
    if [ "${ERR_COUNT:-0}" -ne 0 ]; then
        echo "[FAIL] error 数 = ${ERR_COUNT}，需要为 0 才能通过"
        RC=2
    fi
fi

# 3. Image 产物存在
if [ "$RC" -eq 0 ]; then
    for prod in "${PRODUCTS[@]}"; do
        if [ -n "$prod" ] && [ ! -f "$prod" ]; then
            echo "[FAIL] 产物缺失: $prod"
            RC=3
        fi
    done
fi

# 4. 模块产物存在（手动指定或自动检测）
if [ "$RC" -eq 0 ] && [ "$NEED_MODULES" -eq 1 ]; then
    declare -A seen=()
    for mod_dir in "${MODULE_DIRS[@]}"; do
        if [ "${seen["$mod_dir"]:-0}" -eq 1 ]; then
            continue
        fi
        seen["$mod_dir"]=1
        ko_count=$(find "$mod_dir" -name "*.ko" -type f 2>/dev/null | wc -l)
        if [ "${ko_count:-0}" -eq 0 ]; then
            echo "[FAIL] 模块目录无 .ko 文件: $mod_dir"
            RC=4
        fi
    done
fi

if [ "$RC" -eq 0 ]; then
    product_list="${PRODUCTS[*]:-无}"
    module_list="${MODULE_DIRS[*]:-无}"
    auto_label=$([ "$AUTO_MODULES" -eq 1 ] && echo "[自动检测]" || echo "")
    echo "[PASS] error 数 = 0 ${auto_label}"
    echo "  Image 产物: ${product_list}"
    echo "  模块产物:   ${module_list}"
else
    echo "[FAIL] 编译验证未通过 (exit code=$RC)"
fi

exit $RC
