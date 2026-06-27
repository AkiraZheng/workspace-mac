#!/bin/bash
# 门禁验证脚本 - 文件存在性 + 内容有效性 + schema_version 校验
# 用法: gate_check.sh <layer> <kernel_repo> <output_dir>

LAYER=$1
KERNEL_REPO=$2
OUTPUT_DIR=$3

if [ -z "$LAYER" ] || [ -z "$KERNEL_REPO" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "用法: gate_check.sh <layer> <kernel_repo> <output_dir>"
    echo "示例: gate_check.sh layer2 /root/code/openeuler/kernel /root/code/openeuler/kernel/patchmerge/patch_merge_HDBSS_output"
    exit 1
fi

CONFIG_PATH="$KERNEL_REPO/patch_analysis/config.json"

# 通用：校验 JSON 文件非空且可解析
check_json_valid() {
    local file="$1"
    local label="$2"
    if [ ! -f "$file" ]; then
        echo "❌ $label 文件缺失: $file"
        return 1
    fi
    if [ ! -s "$file" ]; then
        echo "❌ $label 文件为空: $file"
        return 1
    fi
    if ! python3 -c "import json; json.load(open('$file'))" 2>/dev/null; then
        echo "❌ $label JSON 解析失败: $file"
        return 1
    fi
    return 0
}

# 通用：校验 schema_version 存在且值匹配
check_schema_version() {
    local file="$1"
    local expected="$2"
    local label="$3"
    local actual
    actual=$(python3 -c "
import json
with open('$file') as f:
    d = json.load(f)
    print(d.get('schema_version', 'MISSING'))
" 2>/dev/null)
    if [ "$actual" = "MISSING" ]; then
        echo "❌ $label 缺少 schema_version 字段: $file"
        return 1
    fi
    if [ "$actual" != "$expected" ]; then
        echo "❌ $label schema_version 不兼容: 期望=$expected 实际=$actual 文件=$file"
        echo "   可能原因：上层输出格式已更新但本层未同步，请检查所有层的接口定义"
        return 1
    fi
    return 0
}

case $LAYER in
  layer2)
    # config.json 存在性 + 有效性（固定入口路径）
    check_json_valid "$CONFIG_PATH" "Layer 2 前置" || exit 10

    # config.json 必填字段校验
    MISSING_FIELDS=$(python3 -c "
import json
with open('$CONFIG_PATH') as f:
    c = json.load(f)
required = ['patch_source', 'kernel_repo_path', 'kernel_branch', 'kernel_arch', 'build_cmd', 'output_dir']
missing = [k for k in required if k not in c or not c[k]]
if missing:
    print(', '.join(missing))
" 2>/dev/null)
    if [ -n "$MISSING_FIELDS" ]; then
        echo "❌ config.json 必填字段缺失或为空: $MISSING_FIELDS"
        echo "请回到 Layer 1 重新生成 config.json"
        exit 11
    fi

    # config.json schema_version 校验
    check_schema_version "$CONFIG_PATH" "1.0" "config.json" || exit 12

    # config.json 路径一致性校验
    CONFIG_REPO=$(python3 -c "
import json
with open('$CONFIG_PATH') as f:
    print(json.load(f).get('kernel_repo_path', ''))
" 2>/dev/null)
    if [ -n "$CONFIG_REPO" ] && [ "$CONFIG_REPO" != "$KERNEL_REPO" ]; then
        echo "❌ config.json.kernel_repo_path 与实际仓库路径不一致:"
        echo "   config 中: $CONFIG_REPO"
        echo "   实际传入: $KERNEL_REPO"
        exit 13
    fi

    # 输出目录存在性
    if [ ! -d "$OUTPUT_DIR" ]; then
        echo "❌ 输出目录不存在: $OUTPUT_DIR"
        exit 14
    fi
    ;;

  layer3)
    # revert_candidates.json（在输出目录中）
    check_json_valid "$OUTPUT_DIR/revert_candidates.json" "Layer 3 前置" || exit 20
    HAS_CANDIDATES=$(python3 -c "
import json
with open('$OUTPUT_DIR/revert_candidates.json') as f:
    d = json.load(f)
    if 'candidates' not in d:
        print('missing_candidates_key')
    else:
        print('ok')
" 2>/dev/null)
    if [ "$HAS_CANDIDATES" = "missing_candidates_key" ]; then
        echo "❌ revert_candidates.json 缺少 candidates 数组"
        exit 21
    fi

    # deps_candidates.json
    check_json_valid "$OUTPUT_DIR/deps_candidates.json" "Layer 3 前置" || exit 22
    HAS_DEPS=$(python3 -c "
import json
with open('$OUTPUT_DIR/deps_candidates.json') as f:
    d = json.load(f)
    if 'dependencies' not in d:
        print('missing_dependencies_key')
    else:
        print('ok')
" 2>/dev/null)
    if [ "$HAS_DEPS" = "missing_dependencies_key" ]; then
        echo "❌ deps_candidates.json 缺少 dependencies 数组"
        exit 23
    fi

    # merge_tasks.json
    check_json_valid "$OUTPUT_DIR/merge_tasks.json" "Layer 3 前置" || exit 24
    HAS_MERGE=$(python3 -c "
import json
with open('$OUTPUT_DIR/merge_tasks.json') as f:
    d = json.load(f)
    errors = []
    if 'merge_order' not in d:
        errors.append('missing_merge_order')
    elif not isinstance(d['merge_order'], list) or len(d['merge_order']) == 0:
        errors.append('merge_order_empty')
    for t in d.get('merge_order', []):
        for k in ['task_id', 'patch_file', 'seq', 'action']:
            if k not in t:
                errors.append(f'task_{t.get(\"task_id\",\"?\")}_missing_{k}')
    if errors:
        print(','.join(errors))
    else:
        print('ok')
" 2>/dev/null)
    if [ "$HAS_MERGE" != "ok" ]; then
        echo "❌ merge_tasks.json 内容校验失败: $HAS_MERGE"
        exit 25
    fi

    # merge_tasks.json schema_version 校验
    check_schema_version "$OUTPUT_DIR/merge_tasks.json" "1.0" "merge_tasks.json" || exit 26

    # scene 不能是 unknown
    SCENE=$(python3 -c "
import json
with open('$CONFIG_PATH') as f:
    print(json.load(f).get('scene', 'unknown'))
" 2>/dev/null || echo "unknown")
    if [ "$SCENE" = "unknown" ]; then
      echo "❌ Layer 3 前置条件不满足: scene 仍为 unknown"
      echo "场景问询未完成，请回到 Layer 2 完成 upgrade/backport 选择"
      exit 27
    fi
    ;;

  layer4)
    # merge_tasks.json 必须可读（检查数据完整性）
    check_json_valid "$OUTPUT_DIR/merge_tasks.json" "Layer 4 前置" || exit 30

    # 检查 merge_order 中有 apply 的 task
    HAS_APPLY=$(python3 -c "
import json
with open('$OUTPUT_DIR/merge_tasks.json') as f:
    tasks = json.load(f)
applied = [t for t in tasks.get('merge_order', []) if t.get('action') == 'apply']
if not applied:
    print('no_apply_tasks')
else:
    print('ok')
" 2>/dev/null)
    if [ "$HAS_APPLY" = "no_apply_tasks" ]; then
      echo "⚠️ merge_tasks.json 中无 action=apply 的 patch，无需生成 analyse.md"
    fi
    ;;

  *)
    echo "❌ 未知 Layer: $LAYER"
    echo "支持的 Layer: layer2, layer3, layer4"
    exit 1
    ;;
esac

echo "✅ $LAYER 前置文件验证通过（内容有效性 + schema_version 校验）"
exit 0
