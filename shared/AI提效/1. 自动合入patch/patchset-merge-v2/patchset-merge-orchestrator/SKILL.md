---
name: patchset-merge-orchestrator
description: >
  Patchset-merge 主调度 Skill：协调 Layer 1-4 执行顺序，强制门禁验证，状态恢复机制。
  
  强制执行顺序：
  1. layer1-interaction → 2. layer2-search → 3. layer3-execution → 4. layer4-output
  
  触发关键词："patchset merge"、"merge patchset"、"合入 patch"。
  
  输出文件：state.json（持久化执行状态）
---

# Patchset-Merge Orchestrator

## 概述

主调度 Skill，协调 Layer 1-4 的执行顺序，通过门禁验证和状态文件强制执行流程。

<HARD-GATE>
执行顺序强制锁定，不可跳过、不可逆序：

1. 必须首先调用 layer1-interaction
2. 等待 layer1 完成（config.json 生成）后，才能调用 layer2-search
3. 等待 layer2 完成后，才能调用 layer3-execution
4. 等待 layer3 完成后，才能调用 layer4-output

交互强制规则（AI 不得自主决策）：
5. scene 必须由用户在 Layer 2 步骤 3 中明确选择（upgrade/backport），AI 不得自行推断
6. 任何 patch 的跳过/丢弃决定必须经用户明确确认，AI 不得自行判断"已存在"
7. 每个 patch 必须经过完整的 git am 流程，不得在 APPLY 前预判结果

违反顺序 = 立即中止，输出错误日志
</HARD-GATE>

## Skill 初始化

启动时执行：

```bash
# 检查运行时环境
if [ ! -d "$KERNEL_REPO_PATH" ]; then
  echo "错误：KERNEL_REPO_PATH 未设置或不存在"
  exit 1
fi

# 计算输出目录（从 KERNEL_BRANCH 推导）
if [ -n "$KERNEL_BRANCH" ]; then
  OUTPUT_DIR="$KERNEL_REPO_PATH/patchmerge/${KERNEL_BRANCH}_output"
  if [ -f "$OUTPUT_DIR/state.json" ]; then
    echo "检测到 state.json，进入恢复模式"
    # 根据状态决定从哪一层恢复
  else
    echo "未检测到 state.json，从 Layer 1 开始执行"
  fi
else
  echo "未设置 KERNEL_BRANCH，从 Layer 1 开始执行"
fi
```

## 执行流程

### Phase 0: Skill 初始化 + 状态检查

```bash
# 标记开始时间
START_TIME=$(date +%s)

# 读 state.json（若存在）
OUTPUT_DIR="$KERNEL_REPO_PATH/patchmerge/${KERNEL_BRANCH}_output"
if [ -f "$OUTPUT_DIR/state.json" ]; then
  python3 -c "
import json
with open('$OUTPUT_DIR/state.json') as f:
    state = json.load(f)
    current_layer = state.get('current_layer', 'layer1')
    print(f'Restore from: {current_layer}')
"
fi

# 设置环境变量
export KERNEL_REPO_PATH="$KERNEL_REPO_PATH"
export SCRIPTS_DIR="$(pwd)/scripts"
export REFERENCES_DIR="$(pwd)/references"
```

### Phase 1: 调用 layer1-interaction

**强制前置检查**：无前置条件（Layer 1 是起点）

```bash
echo "=== Layer 1: 用户交互层 ==="

# Skill tool 调用
Skill tool: layer1-interaction
  输入: 用户提供的 patch 合入需求描述
  
# 等待 Skill 返回
echo "Layer 1 完成，输出文件："
ls -la "$KERNEL_REPO_PATH/patch_analysis/config.json"

# 提取输出目录
OUTPUT_DIR=$(python3 -c "
import json
with open('$KERNEL_REPO_PATH/patch_analysis/config.json') as f:
    print(json.load(f)['output_dir'])
")
echo "输出目录: $OUTPUT_DIR"

# 门禁验证（检查 Layer 1 输出）
bash "$SCRIPTS_DIR/gate_check.sh" layer2 "$KERNEL_REPO_PATH" "$OUTPUT_DIR"
if [ $? -ne 0 ]; then
  echo "❌ Layer 1 输出验证失败，中止"
  exit 10
fi

# Write state.json
python3 -c "
import json
from datetime import datetime
state = {
    'session_id': 'patchset-merge-$(date +%s)',
    'kernel_repo': '$KERNEL_REPO_PATH',
    'output_dir': '$OUTPUT_DIR',
    'current_layer': 'layer1',
    'layer_status': {
        'layer1': {
            'status': 'completed',
            'skill_invoked': 'layer1-interaction',
            'output_files': ['config.json'],
            'gate_check_exit_code': 0,
            'completed_at': datetime.now().isoformat()
        }
    }
}
with open('$OUTPUT_DIR/state.json', 'w') as f:
    json.dump(state, f, indent=2)
"

echo "✅ Layer 1 完成，进入 Layer 2"
```

### Phase 2: 调用 layer2-search

**强制前置检查**：config.json 存在

```bash
echo "=== Layer 2: 搜索层 ==="

# 门禁验证（检查 Layer 1 输出）
bash "$SCRIPTS_DIR/gate_check.sh" layer3 "$KERNEL_REPO_PATH" "$OUTPUT_DIR"
if [ $? -ne 0 ]; then
  echo "❌ Layer 2 前置验证失败，中止"
  exit 20
fi

# Skill tool 调用
Skill tool: layer2-search
  输入: config.json
  执行内容:
    - 下载 patch（b4/wget/copy）
    - 检测旧版本（detect_duplicate.py --version-upgrade）
    - 场景问询（upgrade/backport）
    - Subagent: agent_target_revert + agent_upstream_deps（并行）

# 等待 Skill 返回
echo "Layer 2 完成，输出文件："
echo "  Patch 文件："
ls -la /tmp/patches/0*.patch 2>/dev/null | head -3 || echo "    未找到 patch 文件"
echo "  分析文件："
  ls -la "$OUTPUT_DIR/duplicate_analysis.json"
  ls -la "$OUTPUT_DIR/revert_candidates.json"
  ls -la "$OUTPUT_DIR/deps_candidates.json"
  ls -la "$OUTPUT_DIR/merge_tasks.json"

# Write state.json
python3 -c "
import json
with open('$OUTPUT_DIR/state.json') as f:
    state = json.load(f)
state['current_layer'] = 'layer2'
state['layer_status']['layer2'] = {
    'status': 'completed',
    'skill_invoked': 'layer2-search',
    'output_files': ['revert_candidates.json', 'deps_candidates.json', 'merge_tasks.json'],
    'subagents': ['agent_target_revert', 'agent_upstream_deps'],
    'gate_check_exit_code': 0
}
with open('$OUTPUT_DIR/state.json', 'w') as f:
    json.dump(state, f, indent=2)
"

echo "✅ Layer 2 完成，进入 Layer 3"
```

### Phase 3: 调用 layer3-execution

**强制前置检查**：revert_candidates.json + deps_candidates.json + merge_tasks.json + scene 必须是 upgrade/backport

```bash
echo "=== Layer 3: 执行层 ==="

# 门禁验证（检查 Layer 2 输出）
bash "$SCRIPTS_DIR/gate_check.sh" layer3 "$KERNEL_REPO_PATH" "$OUTPUT_DIR"
if [ $? -ne 0 ]; then
  echo "❌ Layer 3 前置验证失败，中止"
  exit 30
fi

# 强制场景检查：scene 不能是 "unknown"
SCENE=$(python3 -c "
import json
with open('$KERNEL_REPO_PATH/patch_analysis/config.json') as f:
    print(json.load(f).get('scene', 'unknown'))
")
if [ "$SCENE" = "unknown" ]; then
  echo "❌ 错误：scene 仍为 unknown，Layer 2 的场景问询未完成"
  echo "请回到 Layer 2 完成场景交互（upgrade/backport）"
  exit 31
fi
echo "✅ 场景已确认: $SCENE"

# Skill tool 调用
Skill tool: layer3-execution
  输入: merge_tasks.json + patch_analysis.json
  状态机: PRECHECK → PRE_REVERT → APPLY → VERIFY_INTENT → BUILD → BUILD_FIX → COMMIT → REVIEW → RECORD → DONE
  每步必须完成 gatekeeper 记录，不可跳过任何一步

# 等待 Skill 返回
echo "Layer 3 完成，输出文件："
  ls -la "$OUTPUT_DIR"/*-analyse.md

# Write state.json
python3 -c "
import json
with open('$OUTPUT_DIR/state.json') as f:
    state = json.load(f)
state['current_layer'] = 'layer3'
state['layer_status']['layer3'] = {
    'status': 'completed',
    'skill_invoked': 'layer3-execution'
}
with open('$OUTPUT_DIR/state.json', 'w') as f:
    json.dump(state, f, indent=2)
"

echo "✅ Layer 3 完成，进入 Layer 4"
```

### Phase 4: 调用 layer4-output

**强制前置检查**：所有 analyse.md 文件存在

```bash
echo "=== Layer 4: 输出层 ==="

# Skill tool 调用
Skill tool: layer4-output
  输入: execution_log.json + 所有 analyse.md

# 等待 Skill 返回
echo "Layer 4 完成，输出文件："
  ls -la "$OUTPUT_DIR/summary.md"
  ls -la "$OUTPUT_DIR/output_report.json"

# Write state.json（最终状态）
python3 -c "
import json
with open('$OUTPUT_DIR/state.json') as f:
    state = json.load(f)
state['current_layer'] = 'layer4'
state['layer_status']['layer4'] = {
    'status': 'completed',
    'skill_invoked': 'layer4-output'
}
state['all_layers_completed'] = True
with open('$OUTPUT_DIR/state.json', 'w') as f:
    json.dump(state, f, indent=2)
"

echo "✅ Layer 4 完成，所有 Layer 执行成功"
```

### Phase 5: 完成

输出执行概览：

```
═══════════════════════════════════════════════════════════════
  Patchset-Merge 分层架构执行完成
═══════════════════════════════════════════════════════════════

执行概览：
  目标仓库:       $KERNEL_REPO_PATH
  Session ID:     <session_id>
  总耗时:         $(($(date +%s) - START_TIME)) 秒
  
Layer 状态：
  Layer 1:        ✅ 已完成（config.json）
  Layer 2:        ✅ 已完成（revert + deps + merge_tasks）
  Layer 3:        ✅ 已完成（所有 analyse.md）
  Layer 4:        ✅ 已完成（summary.md + output_report.json）

输出文件路径：
  $OUTPUT_DIR/summary.md
  
后续操作建议：
  1. 查看 summary.md 了解整体合入经验
  2. 查看 *-analyse.md 了解每个 patch 详细记录
  3. 检查 git log 确认所有 commit 已正确记录
  4. 若需合并到主干，请手工执行 git merge

状态文件：
  $OUTPUT_DIR/state.json（可恢复）

═══════════════════════════════════════════════════════════════
```

## 恢复机制

若执行中断（Session 超时/用户中止），恢复流程：

```bash
# 计算输出目录，检查 state.json
OUTPUT_DIR="$KERNEL_REPO_PATH/patchmerge/${KERNEL_BRANCH}_output"
STATE_FILE="$OUTPUT_DIR/state.json"

if [ -f "$STATE_FILE" ]; then
  CURRENT_LAYER=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['current_layer'])")
  
  # 根据状态恢复
  case $CURRENT_LAYER in
    "layer1")
      # Layer 1 已完成 → 从 Layer 2 继续
      bash "$SCRIPTS_DIR/gate_check.sh" layer2 "$KERNEL_REPO_PATH" "$OUTPUT_DIR"
      # 调用 Layer 2...
      ;;
    "layer2")
      # Layer 2 已完成 → 从 Layer 3 继续
      bash "$SCRIPTS_DIR/gate_check.sh" layer3 "$KERNEL_REPO_PATH" "$OUTPUT_DIR"
      # 调用 Layer 3...
      ;;
    "layer3")
      # Layer 3 已完成 → 从 Layer 4 继续
      bash "$SCRIPTS_DIR/gate_check.sh" layer4 "$KERNEL_REPO_PATH" "$OUTPUT_DIR"
      # 调用 Layer 4...
      ;;
    "layer4")
      echo "所有 Layer 已完成，无需恢复"
      ;;
  esac
fi
```

## 错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| Layer 前置文件缺失 | 门禁验证失败 → 输出缺失文件列表 → 中止 |
| Skill 调用失败 | 输出错误日志 → Write state.json（标记失败）→ 中止 |
| 违反执行顺序 | HARD-GATE 触发 → 立即中止 |

## 关键约束

1. **强制顺序执行** - 不可跳过、不可逆序
2. **门禁验证** - 每进入下一层前强制验证前置文件
3. **状态持久化** - 每层完成后立即 Write state.json
4. **可恢复** - 中断后可从 state.json 恢复

## 文件清单

- `SKILL.md` - 本文件
- `scripts/gate_check.sh` - 门禁验证脚本
- `scripts/validate_json.py` - JSON schema 验证
- `scripts/download_patches.py` - Patch 下载（复用）
- `scripts/detect_duplicate.py` - 旧版本检测（保留，备用）
- `scripts/detect_duplicate_sample.py` - 抽样检测（快速，Layer 2 默认使用）
- `references/layer_interface_schema.md` - 层间接口定义
- `references/state_schema.md` - state.json 定义
- `references/fallback_guide.md` - 降级机制指南