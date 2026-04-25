#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    echo "Usage: $0 <stage> <virtual_address> [vm_id]"
    echo ""
    echo "Stages:"
    echo "  stage1  - Query kernel Stage-1 page tables"
    echo "  stage2  - Query VM Stage-2 page tables"
    echo "  auto    - Auto-detect"
    echo "  list    - List available VMs"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

STAGE=$1
VA=$2
VM_ID=$3

if ! [[ "$VA" =~ ^0x[0-9a-fA-F]+$ ]]; then
    echo -e "${RED}Error: Invalid address format${NC}"
    exit 1
fi

TEMP_DIR="/tmp/kpte_query_$$"
mkdir -p "$TEMP_DIR"

get_first_vm_id() {
    for path in /sys/kernel/debug/kvm/*/stage2_page_tables; do
        if [ -f "$path" ]; then
            echo $(basename $(dirname "$path"))
            return 0
        fi
    done
    return 1
}

list_vms() {
    echo -e "${GREEN}Available VMs:${NC}"
    for path in /sys/kernel/debug/kvm/*/stage2_page_tables; do
        if [ -f "$path" ]; then
            echo "  - $(basename $(dirname "$path"))"
        fi
    done
}

# 使用 Python 进行精确的地址解析（避免 awk 的十六进制问题）
query_stage2_python() {
    local dump_file=$1
    local va=$2
    local vm_id=$3
    
    python3 << EOF
import re
import sys

va_hex = "$va"
va_int = int(va_hex, 16)

found = False
with open("$dump_file", 'r') as f:
    lines = f.readlines()

print("\n{:<20} {:<12} {:<10} {}".format("IPA Range", "Level", "Size", "Attributes"))
print("=" * 80)

for line in lines:
    # 匹配地址行
    match = re.match(r'(0x[0-9a-f]+)-(0x[0-9a-f]+)\s+(\S+)\s+(\S+)\s*(.*)', line.strip())
    if not match:
        continue
    
    start_hex = match.group(1)
    end_hex = match.group(2)
    size = match.group(3)
    level = match.group(4)
    attrs = match.group(5).strip()
    
    start_int = int(start_hex, 16)
    end_int = int(end_hex, 16)
    
    if start_int <= va_int < end_int:
        found = True
        
        # 格式化输出
        range_str = f"{start_hex}-{end_hex}"
        level_str = f"L{level}" if level.isdigit() else level
        attrs_str = attrs if attrs else "(HOLE - no attributes)"
        
        print("{:<20} {:<12} {:<10} {}".format(range_str, level_str, size, attrs_str))
        print("=" * 80)
        
        print("\n📋 Detailed Stage-2 (Guest IPA) Information:")
        if "$vm_id":
            print(f"  VM ID: $vm_id")
        print(f"  Full line: {line.strip()}")
        print(f"  IPA Range: {start_hex} -> {end_hex}")
        print(f"  Page Level: L{level}")
        print(f"  Block Size: {size}")
        
        if not attrs:
            print("\n⚠️  WARNING: This is a HOLE (no actual mapping!)")
            print("  The address range is reserved but not yet mapped.")
            print("  Access will cause a stage2 page fault.")
        else:
            if 'R' in attrs:
                print("  ✓ Read: Allowed")
            if 'W' in attrs:
                print("  ✓ Write: Allowed")
            if 'X' in attrs:
                print("  ✓ Execute: Allowed")
            if 'AF' in attrs:
                print("  ✓ Access Flag: Set")
            if 'NORMAL_FWB' in attrs:
                print("  ✓ Memory Type: Normal (FWB)")
            if 'DEVnGnRE' in attrs:
                print("  ✓ Memory Type: Device-nGnRE")
            if 'BLK' in attrs:
                print("  ✓ Block Mapping: Yes")
        break

if not found:
    print("\n❌ IPA not found in Stage-2 page tables")
    print(f"\n  Address: {va_hex} (decimal: {va_int})")
    print("\n  Nearby ranges:")
    
    # 显示附近的区间
    with open("$dump_file", 'r') as f:
        lines = f.readlines()
    
    prev_end = 0
    for line in lines:
        match = re.match(r'(0x[0-9a-f]+)-(0x[0-9a-f]+)', line)
        if match:
            start = int(match.group(1), 16)
            end = int(match.group(2), 16)
            if start <= va_int < end:
                # 已经在上面处理了
                pass
            elif va_int < start and (not prev_end or prev_end <= va_int):
                print(f"    {line.strip()}")
            prev_end = end
    
    print("\n  Possible reasons:")
    print("    1. Address is in a hole (unmapped region)")
    print("    2. Guest physical address is invalid")
EOF
}

query_stage1_python() {
    local dump_file=$1
    local va=$2
    
    python3 << EOF
import re

va_hex = "$va"
va_int = int(va_hex, 16)

found = False
with open("$dump_file", 'r') as f:
    lines = f.readlines()

print("\n{:<20} {:<12} {:<10} {}".format("VA Range", "Level", "Size", "Attributes"))
print("=" * 80)

for line in lines:
    match = re.match(r'(0x[0-9a-f]+)-(0x[0-9a-f]+)\s+(\S+)\s+(\S+)\s*(.*)', line.strip())
    if not match:
        continue
    
    start_hex = match.group(1)
    end_hex = match.group(2)
    size = match.group(3)
    level = match.group(4)
    attrs = match.group(5).strip()
    
    start_int = int(start_hex, 16)
    end_int = int(end_hex, 16)
    
    if start_int <= va_int < end_int:
        found = True
        
        range_str = f"{start_hex}-{end_hex}"
        
        print("{:<20} {:<12} {:<10} {}".format(range_str, level, size, attrs))
        print("=" * 80)
        
        print("\n📋 Detailed Stage-1 PTE Information:")
        print(f"  Full line: {line.strip()}")
        
        if 'MEM/NORMAL' in attrs:
            print("  ✓ Memory Type: NORMAL")
        if 'MEM/NORMAL-NC' in attrs:
            print("  ✓ Memory Type: NORMAL-NC")
        if 'DEVICE' in attrs:
            print("  ✓ Memory Type: DEVICE")
        if 'RW' in attrs:
            print("  ✓ Permission: Read-Write")
        if 'ro' in attrs:
            print("  ✓ Permission: Read-Only")
        if 'X' in attrs and 'NX' not in attrs:
            print("  ✓ Execute: Allowed")
        if 'NX' in attrs:
            print("  ✓ Execute: Not Allowed")
        break

if not found:
    print("\n❌ VA not found in Stage-1 page tables")
EOF
}

query_stage2() {
    local vm_id=$1
    local auto_selected=false
    
    if [ -z "$vm_id" ]; then
        vm_id=$(get_first_vm_id)
        if [ $? -eq 0 ]; then
            auto_selected=true
        else
            echo -e "${RED}Error: No VM found${NC}"
            list_vms
            return 1
        fi
    fi
    
    local debugfs_path="/sys/kernel/debug/kvm/$vm_id/stage2_page_tables"
    
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Querying Stage-2 Page Tables${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo -e "${YELLOW}Guest IPA: ${GREEN}$VA${NC}"
    echo -e "${YELLOW}VM ID: ${GREEN}$vm_id${NC}"
    if [ "$auto_selected" = true ]; then
        echo -e "${YELLOW}Note: Auto-selected first available VM${NC}"
    fi
    echo ""
    
    if [ ! -f "$debugfs_path" ]; then
        echo -e "${RED}Error: Stage-2 page tables not found${NC}"
        list_vms
        return 1
    fi
    
    local dump_file="$TEMP_DIR/stage2_dump.txt"
    cat "$debugfs_path" > "$dump_file"
    
    query_stage2_python "$dump_file" "$VA" "$vm_id"
}

query_stage1() {
    local debugfs_path="/sys/kernel/debug/kernel_page_tables"
    
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Querying Stage-1 Page Tables${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo -e "${YELLOW}VA: ${GREEN}$VA${NC}"
    echo ""
    
    if [ ! -f "$debugfs_path" ]; then
        echo -e "${RED}Error: $debugfs_path not found${NC}"
        return 1
    fi
    
    local dump_file="$TEMP_DIR/stage1_dump.txt"
    cat "$debugfs_path" > "$dump_file"
    
    query_stage1_python "$dump_file" "$VA"
}

check_debugfs() {
    if ! mount | grep -q debugfs; then
        mount -t debugfs none /sys/kernel/debug 2>/dev/null
    fi
}

main() {
    check_debugfs
    
    case "$STAGE" in
        stage1) query_stage1 ;;
        stage2) query_stage2 "$VM_ID" ;;
        auto) 
            if [[ "$VA" =~ ^0xffff ]]; then
                query_stage1
            else
                query_stage2 "$VM_ID"
            fi
            ;;
        list) list_vms ;;
        *) usage ;;
    esac
    
    rm -rf "$TEMP_DIR"
}

main
