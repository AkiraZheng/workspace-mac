#!/bin/bash
# 门禁验证脚本 - 执行时间 <1秒
# 用法: gate_check.sh <layer> <kernel_repo>

LAYER=$1
KERNEL_REPO=$2

if [ -z "$LAYER" ] || [ -z "$KERNEL_REPO" ]; then
    echo "用法: gate_check.sh <layer> <kernel_repo>"
    echo "示例: gate_check.sh layer2 /root/code/openeuler/kernel"
    exit 1
fi

case $LAYER in
  layer2)
    test -f "$KERNEL_REPO/patch_analysis/config.json" || {
      echo "❌ Layer 2 前置文件缺失: config.json"
      echo "请先完成 Layer 1 (layer1-interaction)"
      exit 10
    }
    ;;
  layer3)
    test -f "$KERNEL_REPO/patch_analysis/revert_candidates.json" || {
      echo "❌ Layer 3 前置文件缺失: revert_candidates.json"
      echo "请先完成 Layer 2 (layer2-search)"
      exit 20
    }
    test -f "$KERNEL_REPO/patch_analysis/deps_candidates.json" || {
      echo "❌ Layer 3 前置文件缺失: deps_candidates.json"
      echo "请先完成 Layer 2 (layer2-search)"
      exit 21
    }
    test -f "$KERNEL_REPO/patch_analysis/merge_tasks.json" || {
      echo "❌ Layer 3 前置文件缺失: merge_tasks.json"
      echo "请先完成 Layer 2 (layer2-search)"
      exit 22
    }
    # 检查 scene 不能是 unknown
    SCENE=$(python3 -c "
import json
with open('$KERNEL_REPO/patch_analysis/config.json') as f:
    print(json.load(f).get('scene', 'unknown'))
" 2>/dev/null || echo "unknown")
    if [ "$SCENE" = "unknown" ]; then
      echo "❌ Layer 3 前置条件不满足: scene 仍为 unknown"
      echo "场景问询未完成，请回到 Layer 2 完成 upgrade/backport 选择"
      exit 23
    fi
    ;;
  layer4)
    ls "$KERNEL_REPO/patch_analysis"/*-analyse.md >/dev/null 2>&1 || {
      echo "❌ Layer 4 前置文件缺失: *-analyse.md 文件不存在"
      echo "请先完成 Layer 3 (layer3-execution)"
      exit 30
    }
    ;;
  *)
    echo "❌ 未知 Layer: $LAYER"
    echo "支持的 Layer: layer2, layer3, layer4"
    exit 1
    ;;
esac

echo "✅ $LAYER 前置文件验证通过"
exit 0