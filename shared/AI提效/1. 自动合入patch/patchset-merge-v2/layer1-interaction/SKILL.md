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
# 当前支持 openEuler 内核仓库的常见基线：OLK-6.6, master, main
# 若目标仓库使用其他基线分支（如 linux-rolling, v6.x 等），
# 自动检测失败时会进入手动输入流程
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

上次配置:
  选项:       [2] 指定外部 .config 文件
  来源路径:   /home/user/my-kernel.config
  时间:       2026-05-30 12:00

是否复用此配置？ [Y/n]
```

- **Y / 回车** → 直接按 `config_preference.json` 中的 option 和路径执行，跳过交互。
  **复用后必须更新 last_used 时间戳**：
  ```bash
  python3 -c "
  import json
  with open('$KERNEL_REPO/.patchmerge/config_preference.json') as f:
      pref = json.load(f)
  pref['last_used'] = '$(date -Iseconds)'
  with open('$KERNEL_REPO/.patchmerge/config_preference.json', 'w') as f:
      json.dump(pref, f, indent=2)
  echo '[CHECK] REUSE_PREFERENCE: option=$CONFIG_OPTION last_used updated'
  "
  ```
- **n** → 清除偏好，进入 4b 完整交互

#### 4b. 完整交互

**用户问询**（先检测 `$KERNEL_REPO/.config` 是否存在，决定选项列表）：

```
═══════════════════════════════════════════════
  .config 来源配置
═══════════════════════════════════════════════

目标仓库: $KERNEL_REPO
{若 $KERNEL_REPO/.config 存在，展示: ⚡ 检测到已有 .config 文件}

请选择 .config 来源:

{若 $KERNEL_REPO/.config 存在:}
[1] 直接使用已有的 .config（检测到存在）
    不做任何修改，直接进入下一步

[2] 使用仓库自带的 defconfig{若已有 .config 则不加 (Recommended)}
    自动扫描 arch/arm64/configs/ 列出可用 defconfig，用户选择一个

[3] 指定外部 .config 文件
    用户输入绝对路径 → cp → make olddefconfig

[4] 合并模式：defconfig + 增量片段
    第 1 步：选基础 defconfig（从 arch/arm64/configs/ 扫描列表，或输入外部路径）
    第 2 步：选增量片段（从 arch/arm64/configs/ 扫描列表，或输入外部路径）
    → merge_config.sh 合并 → make olddefconfig

{若 $KERNEL_REPO/.config 不存在:}
[1] 使用仓库自带的 defconfig (Recommended)
    自动扫描 arch/arm64/configs/ 列出可用 defconfig，用户选择一个

[2] 指定外部 .config 文件
    用户输入绝对路径 → cp → make olddefconfig

[3] 合并模式：defconfig + 增量片段
    第 1 步：选基础 defconfig（从 arch/arm64/configs/ 扫描列表，或输入外部路径）
    第 2 步：选增量片段（从 arch/arm64/configs/ 扫描列表，或输入外部路径）
    → merge_config.sh 合并 → make olddefconfig

请选择: [1] (默认)
```

**各选项实现**：

| 选项 | 执行 |
|------|------|
| [1] 已有 | 检查 `$KERNEL_REPO/.config` 存在且包含 `CONFIG_ARM64=y` → 直接继续，不做任何修改。对应 option=0 |
| [1]/[2] defconfig | `ls $KERNEL_REPO/arch/arm64/configs/*` 列出 defconfig 列表 → 用户选择一个（如 `defconfig`）→ `cp arch/arm64/configs/<选择的config> .config` → `make ARCH=arm64 defconfig`。对应 option=1 |
| [2]/[3] 外部 | 用户输入绝对路径 → 校验文件存在 → `cp <path> .config` → `make ARCH=arm64 olddefconfig`。对应 option=2 |
| [3]/[4] 合并 | **第 1 步**：`ls arch/arm64/configs/*` 列表 + `[0] 手动输入外部路径` → 用户选择基础 config → cp 到 .config<br>**第 2 步**：再次扫描 `arch/arm64/configs/*` 列表 + `[0] 手动输入外部路径` → 用户选增量片段<br>→ `scripts/kconfig/merge_config.sh -O . <基础路径> <增量路径>` → `make ARCH=arm64 olddefconfig`。对应 option=3 |

**注意**：option 编号固定（0=已有, 1=defconfig, 2=外部, 3=合并），与用户面板上看到的序号无关。偏好保存用 option 编号。

**边界处理**：
- 选项 [1]（已有 .config）→ 校验 `.config` 包含 `CONFIG_ARM64=y`，否则拒绝并提示换其他选项
- 选项 defconfig / 合并模式中若 `arch/arm64/configs/` 目录不存在或为空 → 提示找不到 defconfig，改用外部文件
- 外部路径不存在 → 报错，让用户重新输入
- `olddefconfig` / `defconfig` 失败 → 报错退出，提示用户检查 config 文件
- 用户直接回车 → 默认 [1]
- 偏好文件不存在 → 直接进入 4b 完整交互
- 合并模式中 `merge_config.sh` 失败 → 报错，提示用户检查两个 config 文件的兼容性

#### 4c. 架构校验与编译命令

```bash
cd "$KERNEL_REPO"

# 本 skill 专用于 aarch64 架构
if ! grep -q 'CONFIG_ARM64=y' .config 2>/dev/null; then
  echo "❌ 错误：.config 中未检测到 CONFIG_ARM64=y"
  echo "本 skill 仅支持 aarch64 架构，请提供 arm64 的 .config 文件"
  exit 19
fi

KERNEL_ARCH="arm64"

# 构建编译命令
BUILD_CMD="make ARCH=arm64 -j$(nproc)"
if grep -q "tools/perf" .config 2>/dev/null; then
  BUILD_CMD="$BUILD_CMD && make -C tools/perf"
fi

echo "架构校验完成：
  架构: $KERNEL_ARCH
  编译命令: $BUILD_CMD"
```

#### 偏好保存

**选择完成后必须保存偏好**。将以下 shell 变量设为实际值后执行：

```bash
# AI 根据用户选择设置这些变量（必须在 python3 -c 调用前 set）：
# CONFIG_OPTION: 0=已有 .config, 1=defconfig, 2=外部文件, 3=合并模式
# CONFIG_FULL_PATH: option=2 时为外部文件路径，其他为空字符串
# CONFIG_BASE: option=3 时为基础 defconfig 路径，其他为空字符串
# CONFIG_INCREMENTAL: option=3 时为增量片段路径，其他为空字符串

CONFIG_OPTION=0  # ← AI 替换为实际值
CONFIG_FULL_PATH=""  # ← AI 替换为实际值（仅 option=2）
CONFIG_BASE=""  # ← AI 替换为实际值（仅 option=3）
CONFIG_INCREMENTAL=""  # ← AI 替换为实际值（仅 option=3）

mkdir -p "$KERNEL_REPO/.patchmerge"
python3 -c "
import json, os
with open(os.environ['KERNEL_REPO'] + '/.patchmerge/config_preference.json', 'w') as f:
    json.dump({
        'option': int(os.environ['CONFIG_OPTION']),
        'full_config_path': os.environ['CONFIG_FULL_PATH'],
        'base_config': os.environ['CONFIG_BASE'],
        'incremental_path': os.environ['CONFIG_INCREMENTAL'],
        'last_used': '$(date -Iseconds)'
    }, f, indent=2)
" KERNEL_REPO="$KERNEL_REPO" CONFIG_OPTION="$CONFIG_OPTION" \
  CONFIG_FULL_PATH="$CONFIG_FULL_PATH" CONFIG_BASE="$CONFIG_BASE" \
  CONFIG_INCREMENTAL="$CONFIG_INCREMENTAL"

echo "[CHECK] SAVE_PREFERENCE: option=$CONFIG_OPTION → $KERNEL_REPO/.patchmerge/config_preference.json"
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
  编译命令:       $BUILD_CMD
  Upstream 仓库:  ${UPSTREAM_REPO:-无}

是否确认继续？ [Y/n]
```

- **Y/回车** → 继续 Write config.json
- **n** → 输出已解析配置供用户手动调整，中止（exit 20）

### 步骤 6: Write config.json

```bash
# 计算输出目录（分支隔离，避免多分支操作覆盖）
OUTPUT_DIR="$KERNEL_REPO/patchmerge/${KERNEL_BRANCH}_output"
mkdir -p "$KERNEL_REPO/patch_analysis"   # config.json 固定入口
mkdir -p "$OUTPUT_DIR"

cat > "$KERNEL_REPO/patch_analysis/config.json" <<EOF
{
  "schema_version": "1.0",
  "patch_source": "$PATCH_SOURCE",
  "kernel_repo_path": "$KERNEL_REPO",
  "kernel_branch": "$KERNEL_BRANCH",
  "baseline_branch": "$BASELINE_BRANCH",
  "kernel_arch": "$KERNEL_ARCH",
  "build_cmd": "$BUILD_CMD",
  "upstream_repo_path": ${UPSTREAM_REPO:-null},
  "output_dir": "$OUTPUT_DIR",
  "scene": "unknown",
  "user_input_original": "$USER_INPUT",
  "extracted_at": "$(date -Iseconds)"
}
EOF

# 同步归档到输出目录（每次合入一份独立副本，永久保留）
cp "$KERNEL_REPO/patch_analysis/config.json" "$OUTPUT_DIR/"

echo "✅ config.json 已生成"
echo "  入口: $KERNEL_REPO/patch_analysis/config.json"
echo "  输出目录: $OUTPUT_DIR"
```

### 步骤 7: 初始化目录结构

```bash
echo "✅ Layer 1 完成"
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
| .config 非 arm64 架构 | 19 | 输出错误，提示提供 arm64 .config |
| 用户拒绝确认 | 20 | 输出配置，中止 |
| 路径解析失败 | 1 | 提示用户重新输入 |

## 降级机制

无需降级（所有操作都是 Bash 快命令，不会超时）。