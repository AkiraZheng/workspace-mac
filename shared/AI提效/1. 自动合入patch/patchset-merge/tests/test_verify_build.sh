#!/bin/bash
# tests/test_verify_build.sh — verify_build.sh 集成测试（v3: +auto-detect）
set -euo pipefail

SCRIPT="$(dirname "$0")/../scripts/verify_build.sh"
PASS=0
FAIL=0

check() {
    local desc="$1" expected_rc="$2"
    shift 2
    local actual_rc=0
    set +e
    bash "$SCRIPT" "$@" >/dev/null 2>&1
    actual_rc=$?
    set -e
    if [ "$actual_rc" = "$expected_rc" ]; then
        echo "  [OK] $desc"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc (expected rc=$expected_rc, got rc=$actual_rc)"
        FAIL=$((FAIL + 1))
    fi
}

setup_merge_json() {
    local merges_file="$1"
    shift
    local task_id="$1"
    shift
    local json_files=""
    for f in "$@"; do
        json_files="${json_files},\"$f\""
    done
    json_files="${json_files#,}"
    cat > "$merges_file" << EOFJSON
{"merge_order":[{"task_id":"$task_id","files_changed":[$json_files],"execution_log":[]}]}
EOFJSON
}

echo "=== verify_build.sh tests ==="

# --- 基础测试 ---
check "空参数" 1

TMPLOG=$(mktemp)
check "日志不存在" 1 --log /nonexistent.log --product /nonexistent
check "空日志" 1 --log "$TMPLOG" --product /dev/null

echo "error: something failed" > "$TMPLOG"
check "日志有 error" 2 --log "$TMPLOG" --product /dev/null

echo "compilation finished" > "$TMPLOG"
check "产物缺失" 3 --log "$TMPLOG" --product /nonexistent/product

echo "compilation finished" > "$TMPLOG"
check "通过" 0 --log "$TMPLOG" --product "$TMPLOG"

# --- 模块手动指定 ---
MODDIR=$(mktemp -d)
touch "$MODDIR/test.ko"
echo "compilation finished" > "$TMPLOG"
check "手动模块通过" 0 --log "$TMPLOG" --product "$TMPLOG" --modules "$MODDIR"

EMPTY_MODDIR=$(mktemp -d)
check "手动模块无 .ko" 4 --log "$TMPLOG" --product "$TMPLOG" --modules "$EMPTY_MODDIR"

# --- 多产物 ---
echo "compilation finished" > "$TMPLOG"
check "多产物" 0 --log "$TMPLOG" --product "$TMPLOG" --product "$TMPLOG"

# --- 自动检测: --merges-file + --task-id ---
REPO=$(mktemp -d)
MERGE_JSON="$REPO/merge_tasks.json"

# 核心代码 → 不需要模块验证
setup_merge_json "$MERGE_JSON" "0001" "arch/arm64/mm/mmu.c" "kernel/sched/core.c"
echo "compilation finished" > "$TMPLOG"
check "自动: 核心代码" 0 --log "$TMPLOG" --merges-file "$MERGE_JSON" --task-id 0001 --repo-path "$REPO" --product "$TMPLOG"

# 驱动文件 + CONFIG=m → 验证 .ko
cat > "$REPO/.config" << 'EOF'
CONFIG_DRM=m
EOF
setup_merge_json "$MERGE_JSON" "0002" "drivers/gpu/drm/drm_ioctl.c"
MOD_DRM="$REPO/drivers/gpu/drm"
mkdir -p "$MOD_DRM"
touch "$MOD_DRM/drm.ko"
echo "compilation finished" > "$TMPLOG"
check "自动: 驱动模块通过" 0 --log "$TMPLOG" --merges-file "$MERGE_JSON" --task-id 0002 --repo-path "$REPO" --product "$TMPLOG"

# 驱动文件 + 无 .ko → 失败
EMPTY_DRIVER_DIR="$REPO/drivers/irqchip"
mkdir -p "$EMPTY_DRIVER_DIR"
cat > "$REPO/.config" << 'EOF'
CONFIG_IRQCHIP=m
EOF
setup_merge_json "$MERGE_JSON" "0003" "drivers/irqchip/irq-gic.c"
echo "compilation finished" > "$TMPLOG"
check "自动: 驱动模块无 .ko" 4 --log "$TMPLOG" --merges-file "$MERGE_JSON" --task-id 0003 --repo-path "$REPO" --product "$TMPLOG"

# 任务不存在的 task_id
setup_merge_json "$MERGE_JSON" "0001" "arch/arm64/mm/mmu.c"
echo "compilation finished" > "$TMPLOG"
check "自动: task_id 不存在" 0 --log "$TMPLOG" --merges-file "$MERGE_JSON" --task-id 9999 --repo-path "$REPO" --product "$TMPLOG"

# 驱动文件 + 无 .config → 保守验证 .ko（无config时CONFIG匹配跳过，但仍检查.ko）
rm -f "$REPO/.config"
setup_merge_json "$MERGE_JSON" "0004" "drivers/gpu/drm/drm_ioctl.c"
MOD2="$REPO/drivers/gpu/drm"
mkdir -p "$MOD2"
touch "$MOD2/drm.ko"
echo "compilation finished" > "$TMPLOG"
check "自动: 无config保守验证" 0 --log "$TMPLOG" --merges-file "$MERGE_JSON" --task-id 0004 --repo-path "$REPO" --product "$TMPLOG"

# sound 文件
cat > "$REPO/.config" << 'EOF'
CONFIG_SOUND=m
EOF
SOUND_DIR="$REPO/sound/pci/hda"
mkdir -p "$SOUND_DIR"
touch "$SOUND_DIR/snd-hda-intel.ko"
setup_merge_json "$MERGE_JSON" "0005" "sound/pci/hda/hda_codec.c"
echo "compilation finished" > "$TMPLOG"
check "自动: sound 模块" 0 --log "$TMPLOG" --merges-file "$MERGE_JSON" --task-id 0005 --repo-path "$REPO" --product "$TMPLOG"

# 清理
rm -f "$TMPLOG"
rm -rf "$REPO" "$MODDIR" "$EMPTY_MODDIR"

echo ""
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
