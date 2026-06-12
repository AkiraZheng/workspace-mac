---
name: layer1-interaction
description: >
  Patchset-merge 用户交互层：参数解析、校验、模式确认。
  
  强制前置条件：
  1. 由 patchset-merge-orchestrator 调用（不可独立触发）
  2. 用户已提供 patch 合入需求描述
  
  输出文件：config.json
  
  完成后状态：Write state.json: {"layer1": "completed"}
---

# Layer 1 - 用户交互层

## 职责

从用户一句话描述中提取配置、校验路径、确认模式，输出结构化 config.json。

## 执行步骤

### 步骤 1: 解析用户输入（纯 Bash）

从用户描述中提取关键信息：

```bash
USER_INPUT="<用户提供的完整描述>"

# 提取 patch 来源（message-id、URL 或路径）
PATCH_SOURCE=$(echo "$USER_INPUT" | grep -oP '合入\s+(\S+)' | awk '{print $2}' || \
                echo "$USER_INPUT" | grep -oP '把\s+(\S+)' | awk '{print $2}')

# 提取目标仓库路径
KERNEL_REPO=$(echo "$USER_INPUT" | grep -oP '到\s+([^的]+)' | awk '{print $2}' | sed 's/的.*//' || \
              echo "$USER_INPUT" | grep -oP '合入到\s+(\S+)' | awk '{print $3}')

# 提取分支名（若有）
KERNEL_BRANCH=$(echo "$USER_INPUT" | grep -oP '分支\s+(\S+)' | awk '{print $2}' || true)

# 提取 upstream 仓库（若有）
UPSTREAM_REPO=$(echo "$USER_INPUT" | grep -oP 'upstream\s+是\s+(\S+)' | awk '{print $3}' || \
                echo "$USER_INPUT" | grep -oP '源仓库是\s+(\S+)' | awk '{print $3}' || true)
```

### 步骤 2: 路径校验（Bash 工具）

```bash
# 校验目标仓库存在
if [ ! -d "$KERNEL_REPO" ]; then
  echo "❌ 错误：目标仓库不存在: $KERNEL_REPO"
  exit 10
fi

# 校验目标仓库是 git repo
if [ ! -d "$KERNEL_REPO/.git" ]; then
  echo "❌ 错误：目标仓库不是 git 仓库: $KERNEL_REPO"
  exit 11
fi

# 校验 upstream 仓库（若指定）
if [ -n "$UPSTREAM_REPO" ] && [ ! -d "$UPSTREAM_REPO" ]; then
  echo "⚠️ 警告：upstream 仓库不存在，将降级为 metadata 推断"
  UPSTREAM_REPO=""
fi

echo "✅ 路径校验通过"
```

### 步骤 3: 自动配置提取 + 基线分支检测（Bash）

```bash
cd "$KERNEL_REPO"

# 步骤 3.5: 检测并选择干净的基线分支
# 注意：架构检测和编译命令在步骤 4（.config 配置完成后）执行
echo "检测基线分支..."

# 定义已知基线分支列表（优先级：从高到低）
KNOWN_BASELINES=(
  "OLK-6.6"     # openEuler 常用基线
  "master"      # 标准 master 分支
  "main"        # GitHub 标准 main 分支
)

# 检测当前分支状态
CURRENT_BRANCH=$(git branch --show-current)
IS_CLEAN=$(git status --porcelain 2>/dev/null | wc -l)
IS_BASELINE=false

# 检查当前分支是否是已知基线
for baseline in $KNOWN_BASELINES; do
  if [ "$CURRENT_BRANCH" = "$baseline" ]; then
    IS_BASELINE=true
    break
  fi
done

# 输出当前状态
echo "当前分支: $CURRENT_BRANCH
  干净状态: $([ $IS_CLEAN -eq 0 ] && echo '干净' || echo '有未提交改动')
  基线类型: $([ $IS_BASELINE = true ] && echo '已知基线' || echo '非基线分支')"

# 自动选择基线分支逻辑
if [ $IS_CLEAN -eq 0 ] && [ $IS_BASELINE = true ]; then
  # 当前分支是干净的基线 → 使用当前分支
  BASELINE_BRANCH="$CURRENT_BRANCH"
  echo "✅ 当前分支是干净的基线，使用: $BASELINE_BRANCH"
  
elif [ -n "$KERNEL_BRANCH" ]; then
  # 用户指定了分支 → 检查是否是干净的基线
  # 切换到用户指定的分支
  git checkout "$KERNEL_BRANCH" 2>/dev/null || {
    echo "❌ 错误：用户指定的分支不存在: $KERNEL_BRANCH"
    exit 12
  }
  
  IS_CLEAN=$(git status --porcelain 2>/dev/null | wc -l)
  if [ $IS_CLEAN -ne 0 ]; then
    echo "❌ 错误：用户指定的分支不干净: $KERNEL_BRANCH"
    echo "   请选择一个干净的基线分支或先提交/清理改动"
    exit 13
  fi
  
  BASELINE_BRANCH="$KERNEL_BRANCH"
  echo "✅ 使用用户指定的干净分支: $BASELINE_BRANCH"
  
else
  # 当前分支不干净或不是基线 → 自动选择基线
  echo "⚠️ 当前分支不适合作为基线，自动选择基线分支..."
  
  FOUND_BASELINE=""
  for baseline in $KNOWN_BASELINES; do
    # 检查基线分支是否存在
    if git rev-parse --verify "$baseline" >/dev/null 2>&1; then
      # 检查基线分支是否干净（远程跟踪）
      REMOTE_BRANCH="origin/$baseline"
      if git rev-parse --verify "$REMOTE_BRANCH" >/dev/null 2>&1; then
        # 检查本地基线分支是否与远程一致
        LOCAL_COMMIT=$(git rev-parse "$baseline")
        REMOTE_COMMIT=$(git rev-parse "$REMOTE_BRANCH")
        if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
          FOUND_BASELINE="$baseline"
          echo "  ✅ 找到干净基线: $baseline (与远程一致)"
          break
        else
          echo "  ⚠️ $baseline 存在但与远程不一致"
        fi
      else
        echo "  ⚠️ $baseline 无远程跟踪"
      fi
    else
      echo "  ⚠️ $baseline 不存在"
    fi
  done
  
  if [ -z "$FOUND_BASELINE" ]; then
    # 没找到干净的基线分支 → 询问用户
    echo "
═══════════════════════════════════════════════
  ⚠️ 未找到自动干净的基线分支
═══════════════════════════════════════════════

检测到的基线分支状态：
$(for baseline in $KNOWN_BASELINES; do
  if git rev-parse --verify "$baseline" >/dev/null 2>&1; then
    status=$(git status --porcelain "$baseline" 2>/dev/null | wc -l)
    echo "  $baseline: $([ $status -eq 0 ] && echo '干净' || echo '有改动')"
  else
    echo "  $baseline: 不存在"
  fi
done)

请选择基线分支：
  [1] 手动输入基线分支名
  [2] 使用当前分支（$CURRENT_BRANCH，将创建新工作分支）
  [3] 中止操作，手动清理后重试

选择: [1] / [2] / [3]"
    read -n 1 -r CHOICE
    echo
    
    case $CHOICE in
      1)
        echo "请输入基线分支名:"
        read -r USER_BASELINE
        git rev-parse --verify "$USER_BASELINE" >/dev/null 2>&1 || {
          echo "❌ 分支不存在: $USER_BASELINE"
          exit 14
        }
        FOUND_BASELINE="$USER_BASELINE"
        ;;
      2)
        # 强制使用当前分支（创建工作分支时会清理）
        FOUND_BASELINE="$CURRENT_BRANCH"
        ;;
      3)
        echo "中止操作"
        exit 15
        ;;
      *)
        echo "无效选择"
        exit 16
        ;;
    esac
  fi
  
  BASELINE_BRANCH="$FOUND_BASELINE"
  echo "✅ 选择基线分支: $BASELINE_BRANCH"
  
  # 切换到基线分支
  git checkout "$BASELINE_BRANCH" 2>/dev/null || {
    echo "❌ 切换基线分支失败"
    exit 17
  }
fi

# 步骤 3.6: 从基线分支创建工作分支（自动）
# 从第一个 patch 的 subject 提取特征名（如果 patch 已下载）
if [ -d "/tmp/patches" ] && ls /tmp/patches/0*.patch >/dev/null 2>&1; then
  FEATURE=$(python3 -c "
import re
from pathlib import Path
patches = sorted(Path('/tmp/patches').glob('0*.patch'))
if patches:
    for line in patches[0].read_text(errors='replace').split('\n')[:30]:
        m = re.match(r'Subject:\s*(.+)', line)
        if m:
            for w in m.group(1).split():
                clean = w.strip(':,;.()\"')
                if clean.isupper() and len(clean) >= 3:
                    print(clean)
                    exit(0)
print('patchset')
" 2>/dev/null || echo "patchset")
else
  FEATURE="patchset"
fi

# 工作分支名
WORK_BRANCH="patch_merge_${FEATURE}"

# 若分支已存在，加 _v2 / _v3 后缀
SUFFIX=""
COUNT=1
while git rev-parse --verify "${WORK_BRANCH}${SUFFIX}" >/dev/null 2>&1; do
  COUNT=$((COUNT + 1))
  SUFFIX="_v${COUNT}"
done
WORK_BRANCH="${WORK_BRANCH}${SUFFIX}"

# 创建工作分支
git checkout -b "$WORK_BRANCH" || {
  echo "❌ 创建工作分支失败"
  exit 18
}

KERNEL_BRANCH="$WORK_BRANCH"
echo "✅ 工作分支已创建: $KERNEL_BRANCH (基于基线: $BASELINE_BRANCH)"

echo "配置提取完成：
  基线分支: $BASELINE_BRANCH
  工作分支: $KERNEL_BRANCH"
```

### 步骤 4: .config 来源配置

编译验证开始前，需要确定 `.config` 文件的来源。**只执行一次**，后续所有 checkpoint 编译复用此文件。

#### 4a. 复用检查

读取 `$KERNEL_REPO/.patchmerge/config_preference.json`。若存在，展示上次配置并询问是否复用：

```
═══════════════════════════════════════════════
  .config 来源配置 — 检测到上次配置
═══════════════════════════════════════════════

目标仓库: $KERNEL_REPO
架构: $KERNEL_ARCH

上次配置:
  选项:       [2] 提供完整 .config 文件
  来源路径:   /home/user/my-kernel.config
  时间:       2026-05-30 12:00

是否复用此配置？ [Y/n]
```

- **Y / 回车** → 直接按 `config_preference.json` 中的 option 和路径执行，跳过交互
- **n** → 清除偏好，进入 4b 完整交互

#### 4b. 完整交互

**用户问询**：

```
═══════════════════════════════════════════════
  .config 来源配置
═══════════════════════════════════════════════

目标仓库: $KERNEL_REPO
架构: $KERNEL_ARCH

请选择 .config 来源:

[1] 使用目标仓库已有 .config 文件
    (不做任何修改，直接进入下一步)

[2] 提供完整 .config 文件
    从指定路径 copy → make olddefconfig

[3] 提供增量 config 片段
    选基础 config + 增量片段 → merge → olddefconfig

  请选择: [1] / [2] / [3] (默认 [1])
```

**各选项实现 + 偏好保存**：

| 选项 | 执行 | 保存到 config_preference.json |
|------|------|-----|
| [1] | 检查 `$KERNEL_REPO/.config` 存在 → 继续 | `{"option": 1}` |
| [2] | 用户输入路径 → `cp <path> $KERNEL_REPO/.config` → `make ARCH=$KERNEL_ARCH olddefconfig` | `{"option": 2, "full_config_path": "<用户输入的路径>"}` |
| [3] | a. 扫描 `$KERNEL_REPO/arch/$KERNEL_ARCH/configs/*` 列出让用户选基础 config<br>b. 再次扫描同目录列出增量 config，末尾加 `[0] 手动输入外部文件路径` 供用户自由输入<br>c. `$KERNEL_REPO/scripts/kconfig/merge_config.sh -O "$KERNEL_REPO" <base> <incremental>`<br>d. `make ARCH=$KERNEL_ARCH olddefconfig` | `{"option": 3, "base_config": "<选中的基础config>", "incremental_path": "<选中的增量或用户输入的路径>"}` |

**偏好保存**（选项 2/3 执行成功后）：

```bash
mkdir -p "$KERNEL_REPO/.patchmerge"
python3 -c "
import json
with open('$KERNEL_REPO/.patchmerge/config_preference.json', 'w') as f:
    json.dump({
        'option': <opt>,
        'full_config_path': '<path>',
        'base_config': '<base>',
        'incremental_path': '<incr>',
        'last_used': '$(date -Iseconds)'
    }, f, indent=2)
"
```

**边界处理**：
- 路径不存在 → 报错，让用户重新输入
- `olddefconfig` 失败 → 报错退出，提示用户检查 config 文件
- 用户直接回车 → 默认 [1]
- 偏好文件不存在 → 直接进入 4b 完整交互

#### 4d. 架构检测与编译命令（.config 就绪后执行）

```bash
cd "$KERNEL_REPO"

# 提取架构
KERNEL_ARCH=$(grep -oP 'CONFIG_ARM64=y' .config 2>/dev/null | sed 's/CONFIG_ARM64=y/arm64/' || echo "x86_64")

# 构建编译命令
BUILD_CMD="make ARCH=$KERNEL_ARCH -j$(nproc)"
if grep -q "tools/perf" .config 2>/dev/null; then
  BUILD_CMD="$BUILD_CMD && make -C tools/perf"
fi

echo "架构检测完成：
  架构: $KERNEL_ARCH
  编译命令: $BUILD_CMD"
```

### 步骤 5: 场景确认（Question 工具）

使用 Question 工具展示配置并确认：

```
═══════════════════════════════════════════════
  Patchset-merge 配置确认
═══════════════════════════════════════════════

已解析配置：
  Patch 来源:     $PATCH_SOURCE
  目标仓库:       $KERNEL_REPO
  基线分支:       $BASELINE_BRANCH
  工作分支:       $KERNEL_BRANCH (自动创建)
  目标架构:       $KERNEL_ARCH
  编译命令:       $BUILD_CMD
  Upstream 仓库:  ${UPSTREAM_REPO:-无}

是否确认继续？ [Y/n]
```

- **Y/回车** → 继续 Write config.json
- **n** → 输出已解析配置供用户手动调整，中止（exit 20）

### 步骤 6: Write config.json

```bash
mkdir -p "$KERNEL_REPO/patch_analysis"

cat > "$KERNEL_REPO/patch_analysis/config.json" <<EOF
{
  "patch_source": "$PATCH_SOURCE",
  "kernel_repo_path": "$KERNEL_REPO",
  "kernel_branch": "$KERNEL_BRANCH",
  "baseline_branch": "$BASELINE_BRANCH",
  "kernel_arch": "$KERNEL_ARCH",
  "build_cmd": "$BUILD_CMD",
  "upstream_repo_path": ${UPSTREAM_REPO:-null},
  "scene": "unknown",
  "user_input_original": "$USER_INPUT",
  "extracted_at": "$(date -Iseconds)"
}
EOF

echo "✅ config.json 已生成"
```

### 步骤 7: 初始化目录结构

```bash
mkdir -p "$KERNEL_REPO/.patchmerge"

echo "✅ Layer 1 完成：config.json 已生成"
echo "输出文件路径：$KERNEL_REPO/patch_analysis/config.json"
```

## 错误处理

| 错误类型 | 退出码 | 处理方式 |
|---------|--------|---------|
| 目标仓库不存在 | 10 | 输出错误，中止 |
| 目标仓库非 git repo | 11 | 输出错误，中止 |
| 用户指定分支不存在 | 12 | 输出错误，中止 |
| 用户指定分支不干净 | 13 | 输出错误，中止 |
| 手动输入基线分支不存在 | 14 | 输出错误，中止 |
| 用户中止操作 | 15 | 输出提示，中止 |
| 无效选择 | 16 | 输出错误，中止 |
| 切换基线分支失败 | 17 | 输出错误，中止 |
| 创建工作分支失败 | 18 | 输出错误，中止 |
| 用户拒绝确认 | 20 | 输出配置，中止 |
| 路径解析失败 | 1 | 提示用户重新输入 |

## 降级机制

无需降级（所有操作都是 Bash 快命令，不会超时）。