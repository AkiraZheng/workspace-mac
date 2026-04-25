#!/bin/bash
# run_vm.sh - QEMU 虚拟机管理脚本（支持 KVM/HVF 模式）
#
# 用法: ./run_vm.sh [command] [mode]
#
# 模式:
#   kvm         使用 KVM 加速（需要 Linux + KVM 支持）
#   nokvm       使用 HVF 加速（macOS 默认，推荐）
#
# 示例:
#   ./run_vm.sh start kvm      # 以 KVM 模式启动
#   ./run_vm.sh start nokvm    # 以 HVF 模式启动
#   ./run_vm.sh backup         # 手动备份当前状态
#   ./run_vm.sh reset nokvm    # 重置并以 HVF 模式启动

set -e

# ========== QEMU 镜像工作原理 ==========
#
# 差异镜像（qcow2 with backing file）:
#
#   base.qcow2 (36GB)     ← 完整系统镜像，只读基础
#   current.qcow2 (KB级)   ← 差异镜像，只记录对base的变更
#
#   虚拟机运行时 = base.qcow2 + current.qcow2 的叠加
#
#   ┌─────────────────────────────────────────────────────────┐
#   │  虚拟机看到的文件系统                        │
#   │  = base镜像数据 + current差异数据              │
#   └─────────────────────────────────────────────────────────┘
#              ↑                      ↑
#         (只读引用)           (写入变更)
#
# 注意事项:
#   1. current.qcow2 内部有 base.qcow2 的路径引用
#   2. 单独移动 current.qcow2 到其他机器无法使用
#   3. base.qcow2 保持不变，可以随时重置回原始状态
#   4. commit 后，base.qcow2 被修改，变成完整独立镜像
#
# ========== 配置 ==========
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_IMG="${BASE_IMG:-${SCRIPT_DIR}/openEuler-24.03-LTS-aarch64.qcow2}"
CURRENT_IMG="${CURRENT_IMG:-${SCRIPT_DIR}/current.qcow2}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-${SCRIPT_DIR}/snapshots}"
BIOS="${BIOS:-${SCRIPT_DIR}/edk2-aarch64-code.fd}"
KERNEL_DIR="${KERNEL_DIR:-${SCRIPT_DIR}/../shared}"

# CPU 和内存配置
SMP="${SMP:-8}"
MEMORY="${MEMORY:-6G}"

# SSH 端口映射
SSH_PORT="${SSH_PORT:-2222}"

CMD="${1:-start}"
MODE="${2:-nokvm}"

mkdir -p "$SNAPSHOT_DIR"

# ========== 函数 ==========

start_vm() {
    # 启动前自动备份当前状态
    if [ -f "$CURRENT_IMG" ]; then
        BACKUP="$SNAPSHOT_DIR/snapshot_before_start_$(date +%Y%m%d_%H%M%S).qcow2"
        echo "[*] 启动前备份: $BACKUP"
        cp "$CURRENT_IMG" "$BACKUP"
    fi

    # 检查镜像是否存在
    if [ ! -f "$CURRENT_IMG" ]; then
        echo "[*] 当前镜像不存在，创建差异镜像..."
        qemu-img create -f qcow2 -F qcow2 -b "$BASE_IMG" "$CURRENT_IMG" > /dev/null 2>&1
    fi

    echo "[*] 启动虚拟机 (模式: $MODE)"
    echo "    镜像: $CURRENT_IMG"
    echo "    SSH 端口: $SSH_PORT"

    case "$MODE" in
        kvm)
            # KVM 模式 - 需要 Linux 宿主机
            # 使用 virtio-mmio 或 PCI 总线
            qemu-system-aarch64 \
                -machine virt,virtualization=true \
                -cpu max \
                -smp "$SMP" \
                -m "$MEMORY" \
                -bios "$BIOS" \
                -drive file="$CURRENT_IMG",if=none,id=hd0,format=qcow2 \
                -device virtio-blk-pci,drive=hd0 \
                -netdev user,id=net0,hostfwd=tcp::${SSH_PORT}-:22 \
                -device virtio-net-pci,netdev=net0 \
                -virtfs local,path="$KERNEL_DIR",mount_tag=host-kernel,security_model=mapped \
                -nographic \
                -rtc clock=host,base=localtime
            ;;
        nokvm|hv)
            # HVF 模式 - macOS Apple Silicon
            qemu-system-aarch64 \
                -machine virt,accel=hvf \
                -cpu max \
                -smp "$SMP" \
                -m "$MEMORY" \
                -bios "$BIOS" \
                -drive file="$CURRENT_IMG",if=none,id=hd0,format=qcow2 \
                -device virtio-blk-pci,drive=hd0 \
                -netdev user,id=net0,hostfwd=tcp::${SSH_PORT}-:22 \
                -device virtio-net-pci,netdev=net0 \
                -virtfs local,path="$KERNEL_DIR",mount_tag=host-kernel,security_model=mapped \
                -nographic \
                -rtc clock=host,base=localtime
            ;;
        *)
            echo "[!] 未知模式: $MODE"
            echo "    可用模式: kvm, nokvm"
            exit 1
            ;;
    esac
}

stop_vm() {
    echo "[*] 停止虚拟机..."
    # 尝试通过 SSH 优雅关闭
    ssh -p "$SSH_PORT" root@127.0.0.1 "halt" 2>/dev/null || true
    # 杀掉 QEMU 进程
    pkill -f "qemu-system-aarch64.*$CURRENT_IMG" 2>/dev/null || true
    echo "[+] 完成"
}

reset_vm() {
    echo "[!] 重置模式：丢弃所有修改，从基础镜像重新开始"
    if [ -f "$CURRENT_IMG" ]; then
        BACKUP="$SNAPSHOT_DIR/snapshot_before_reset_$(date +%Y%m%d_%H%M%S).qcow2"
        echo "[*] 重置前备份到: $BACKUP"
        cp "$CURRENT_IMG" "$BACKUP"
        rm -f "$CURRENT_IMG"
    fi
    qemu-img create -f qcow2 -F qcow2 -b "$BASE_IMG" "$CURRENT_IMG" > /dev/null 2>&1
    echo "[+] 已重置，下次启动时生效"
}

backup_vm() {
    BACKUP="$SNAPSHOT_DIR/snapshot_$(date +%Y%m%d_%H%M%S).qcow2"
    if [ ! -f "$CURRENT_IMG" ]; then
        echo "[!] 当前镜像不存在，无法备份"
        exit 1
    fi
    echo "[*] 创建快照备份: $BACKUP"
    cp "$CURRENT_IMG" "$BACKUP"
    echo "[+] 备份完成"
}

list_snapshots() {
    echo "[*] 可用快照:"
    if [ ! -d "$SNAPSHOT_DIR" ] || [ -z "$(ls -A "$SNAPSHOT_DIR" 2>/dev/null)" ]; then
        echo "    (无)"
    else
        ls -1t "$SNAPSHOT_DIR"/*.qcow2 2>/dev/null | while read f; do
            SIZE=$(ls -lh "$f" | awk '{print $5}')
            echo "    $(basename "$f") ($SIZE)"
        done
    fi
    echo ""
    echo "[*] 当前镜像:"
    if [ -f "$CURRENT_IMG" ]; then
        SIZE=$(ls -lh "$CURRENT_IMG" | awk '{print $5}')
        echo "    $CURRENT_IMG ($SIZE)"
    else
        echo "    (不存在)"
    fi
}

restore_vm() {
    SNAPSHOT="$2"
    if [ -z "$SNAPSHOT" ]; then
        echo "[!] 用法: $0 restore <snapshot_file>"
        echo "[*] 可用快照:"
        ls -1 "$SNAPSHOT_DIR"/*.qcow2 2>/dev/null || echo "    (无)"
        exit 1
    fi

    # 支持简写或完整路径
    if [ ! -f "$SNAPSHOT" ]; then
        SNAPSHOT="$SNAPSHOT_DIR/$SNAPSHOT"
    fi

    if [ ! -f "$SNAPSHOT" ]; then
        echo "[!] 快照文件不存在: $SNAPSHOT"
        exit 1
    fi

    # 恢复前备份当前状态
    if [ -f "$CURRENT_IMG" ]; then
        BACKUP="$SNAPSHOT_DIR/snapshot_before_restore_$(date +%Y%m%d_%H%M%S).qcow2"
        echo "[*] 恢复前备份当前状态: $BACKUP"
        cp "$CURRENT_IMG" "$BACKUP"
    fi

    echo "[*] 恢复快照: $SNAPSHOT"
    cp "$SNAPSHOT" "$CURRENT_IMG"
    echo "[+] 恢复完成"
}

delete_snapshot() {
    SNAPSHOT="$2"
    if [ -z "$SNAPSHOT" ]; then
        echo "[!] 用法: $0 delete <snapshot_file>"
        echo "[*] 可用快照:"
        ls -1tr "$SNAPSHOT_DIR"/*.qcow2 2>/dev/null || echo "    (无)"
        exit 1
    fi

    # 支持简写或完整路径
    if [ ! -f "$SNAPSHOT" ]; then
        SNAPSHOT="$SNAPSHOT_DIR/$SNAPSHOT"
    fi

    if [ ! -f "$SNAPSHOT" ]; then
        echo "[!] 快照文件不存在: $SNAPSHOT"
        exit 1
    fi

    echo "[!] 删除快照: $SNAPSHOT"
    rm -f "$SNAPSHOT"
    echo "[+] 已删除"
}

delete_all_snapshots() {
    if [ ! -d "$SNAPSHOT_DIR" ] || [ -z "$(ls -A "$SNAPSHOT_DIR" 2>/dev/null)" ]; then
        echo "[*] 没有快照可删除"
        return
    fi

    echo "[!] 即将删除所有快照:"
    ls -1t "$SNAPSHOT_DIR"/*.qcow2 2>/dev/null | while read f; do
        echo "    $f"
    done
    echo ""
    read -p "[?] 确认删除? (y/N): " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        rm -f "$SNAPSHOT_DIR"/*.qcow2
        echo "[+] 已删除所有快照"
    else
        echo "[*] 已取消"
    fi
}

commit_changes() {
    echo "================================================================================"
    echo "  COMMIT 警告和说明"
    echo "================================================================================"
    echo ""
    echo "  [操作] 将 current.qcow2 的变更合并到 base.qcow2"
    echo ""
    echo "  [原理]"
    echo "    当前结构："
    echo "      base.qcow2 (36GB)     ← 原始系统镜像（只读基础）"
    echo "      current.qcow2 (KB级)   ← 差异镜像（只记录变更）"
    echo "    虚拟机运行时 = base.qcow2 + current.qcow2 的叠加"
    echo ""
    echo "    commit 后："
    echo "      base.qcow2             ← 变成完整独立镜像（包含所有变更）"
    echo "      current.qcow2           ← 仍是差异镜像（内容不变）"
    echo ""
    echo "  [影响]"
    echo "    1. base.qcow2 可移动到其他机器独立使用"
    echo "    2. 所有旧快照将失效（restore 可能无法正常工作）"
    echo "    3. 无法回滚到 commit 前的状态"
    echo ""
    echo "  [建议]"
    echo "    1. 先备份当前 base.qcow2（重要！）"
    echo "    2. commit 后验证虚拟机能正常启动"
    echo "    3. 验证通过后执行: $0 reset 刷新 current.qcow2"
    echo ""
    echo "================================================================================"
    echo ""

    if [ ! -f "$CURRENT_IMG" ]; then
        echo "[!] 当前镜像不存在: $CURRENT_IMG"
        exit 1
    fi

    if [ ! -f "$BASE_IMG" ]; then
        echo "[!] 基础镜像不存在: $BASE_IMG"
        exit 1
    fi

    # 显示快照信息
    if [ -d "$SNAPSHOT_DIR" ] && [ -n "$(ls -A "$SNAPSHOT_DIR" 2>/dev/null)" ]; then
        echo "[*] 检测到快照文件，commit 后将失效："
        ls -1t "$SNAPSHOT_DIR"/*.qcow2 2>/dev/null | while read f; do
            echo "    $f"
        done
        echo ""
    else
        echo "[*] 没有检测到快照文件"
        echo ""
    fi

    # 用户确认
    read -p "[?] 确认执行 commit？输入 y 继续: " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "[*] 已取消"
        exit 0
    fi

    echo ""
    echo "[*] 正在执行 commit..."
    echo ""

    # 删除失效的快照
    if [ -d "$SNAPSHOT_DIR" ] && [ -n "$(ls -A "$SNAPSHOT_DIR" 2>/dev/null)" ]; then
        echo "[!] 删除失效的快照..."
        rm -f "$SNAPSHOT_DIR"/*.qcow2
        echo "[+] 已删除所有快照"
        echo ""
    fi

    # 执行 commit
    qemu-img commit "$CURRENT_IMG"

    echo "================================================================================"
    echo "  COMMIT 完成"
    echo "================================================================================"
    echo ""
    echo "  [状态]"
    echo "    base.qcow2     ← 已更新为完整独立镜像"
    echo "    current.qcow2   ← 仍是差异镜像（可继续使用）"
    echo ""
    echo "  [下一步]"
    echo "    1. 启动虚拟机验证: $0 start"
    echo "    2. 验证通过后刷新: $0 reset"
    echo ""
    echo "  [说明]"
    echo "    base.qcow2 现在是完整镜像，可安全移动到其他机器"
    echo "    current.qcow2 基于 base.qcow2，reset 后将基于新 base"
    echo "================================================================================"
}


show_status() {
    echo "[*] 状态信息:"
    echo "    基础镜像: $BASE_IMG"
    echo "    当前镜像: $CURRENT_IMG"
    echo "    快照目录: $SNAPSHOT_DIR"
    echo "    BIOS: $BIOS"
    echo "    内核目录: $KERNEL_DIR"
    echo "    CPU: $SMP 核"
    echo "    内存: $MEMORY"
    echo "    SSH 端口: $SSH_PORT"
    echo ""
    if [ -f "$CURRENT_IMG" ]; then
        SIZE=$(ls -lh "$CURRENT_IMG" | awk '{print $5}')
        echo "    当前状态: 已创建 ($SIZE)"
    else
        echo "    当前状态: (未创建)"
    fi
}

show_help() {
    echo "用法: $0 [command] [mode]"
    echo ""
    echo "命令:"
    echo "  start       启动虚拟机（默认）"
    echo "               [镜像] 基于 current.qcow2（继续上次状态）"
    echo "               [快照] 启动前自动备份"
    echo ""
    echo "  stop        停止虚拟机"
    echo "               [镜像] 基于 current.qcow2"
    echo "               [快照] 不备份（无数据修改）"
    echo ""
    echo "  reset       重置到基础镜像（丢弃所有修改）"
    echo "               [镜像] 基于 base qcow2 重新创建差异镜像"
    echo "                       回到最初装好的 openEuler 系统状态"
    echo "               [快照] 重置前自动备份"
    echo ""
    echo "  backup      手动创建快照备份"
    echo "               [镜像] 基于 current.qcow2"
    echo "               [快照] 立即创建快照"
    echo ""
    echo "  commit      将当前变更合并到 base.qcow2"
    echo "               [原理] 把差异数据写入 base，base 变成完整独立镜像"
    echo "               [警告] commit 后无法回滚到旧快照，快照将失效"
    echo "                       合并后 base 可移动到其他机器独立使用"
    echo ""
    echo "  list        列出可用快照"
    echo "               [镜像] 无影响"
    echo "               [快照] 不备份（只读）"
    echo ""
    echo "  restore     恢复到指定快照"
    echo "               [镜像] 基于指定快照覆盖 current.qcow2"
    echo "               [快照] 恢复前自动备份"
    echo ""
    echo "  delete      删除指定快照"
    echo "               [镜像] 无影响"
    echo "               [警告] 删除后无法恢复"
    echo "               [用法] $0 delete <snapshot_file>"
    echo ""
    echo "  deleteall   删除所有快照"
    echo "               [镜像] 无影响"
    echo "               [警告] 删除后无法恢复"
    echo ""
    echo "  status      查看当前状态"
    echo "               [镜像] 无影响"
    echo "               [快照] 不备份（只读）"
    echo ""
    echo "模式:"
    echo "  kvm         使用 KVM 加速（需要 Linux + KVM）"
    echo "  nokvm       使用 HVF 加速（macOS 默认，推荐）"
    echo ""
    echo "示例:"
    echo "  $0 start nokvm    # 以 HVF 模式启动（默认）"
    echo "  $0 reset nokvm    # 重置并以 HVF 模式启动"
    echo "  $0 backup         # 备份当前状态"
    echo "  $0 restore snapshot_20260404_120000.qcow2"
}

# ========== 主逻辑 ==========

case "$CMD" in
    start)
        start_vm
        ;;
    stop)
        stop_vm
        ;;
    reset)
        reset_vm
        ;;
    backup)
        backup_vm
        ;;
    list)
        list_snapshots
        ;;
    restore)
        restore_vm "$@"
        ;;
    commit)
        commit_changes
        ;;
    delete)
        delete_snapshot "$@"
        ;;
    deleteall)
        delete_all_snapshots
        ;;
    status)
        show_status
        ;;
    help|-h|--help)
        show_help
        ;;
    *)
        echo "[!] 未知命令: $CMD"
        show_help
        exit 1
        ;;
esac
