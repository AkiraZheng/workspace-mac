#!/bin/bash

#
# demo.sh - 用户态页表属性分析演示脚本
#
# 该脚本演示完整的页表属性获取和分析流程
#

echo "========================================"
echo "用户态页表属性分析演示"
echo "========================================"
echo ""

# ========================================
# 步骤 1: 编译工具和程序
# ========================================
echo "=== 步骤 1: 编译工具和程序 ==="
echo ""

# 编译 page-types (如果还没编译)
if [ ! -f "./page-types" ]; then
    echo "page-types 工具已存在，跳过编译"
else
    echo "编译 show_addr.c..."
fi

gcc -o show_addr show_addr.c
if [ $? -eq 0 ]; then
    echo "编译成功"
else
    echo "编译失败"
    exit 1
fi

echo ""

# ========================================
# 步骤 2: 准备环境
# ========================================
echo "=== 步骤 2: 准备环境 ==="
echo ""

# 禁用 ASLR 以获得稳定地址
echo 0 > /proc/sys/kernel/randomize_va_space
echo "ASLR 已禁用: $(cat /proc/sys/kernel/randomize_va_space)"

# 创建测试文件（用于 mmap 测试）
TEST_FILE=/tmp/demo_testfile
dd if=/dev/zero of=$TEST_FILE bs=1K count=512 2>/dev/null

echo ""

# ========================================
# 步骤 3: 启动测试程序
# ========================================
echo "=== 步骤 3: 启动测试程序 ==="
echo ""

# 后台运行 show_addr
./show_addr &
PID=$!
echo "测试进程 PID: $PID"
echo "等待进程启动..."
sleep 1.5

# 获取进程地址信息
echo ""
echo "=== 进程地址空间 ==="
echo ""

echo "主要映射区域："
sudo cat /proc/$PID/maps | grep -E "\[stack\]|\[heap\]|rw-p 0001" | head -10

echo ""

# ========================================
# 步骤 4: 获取测试地址信息
# ========================================
echo "=== 步骤 4: 分析特定地址 ==="
echo ""

# 获取全局变量地址（在数据段）
GLOBAL_VAR_ADDR=$(sudo cat /proc/$PID/maps | grep "rw-p 0001" | head -1 | awk -F'-' '{print $1}')
echo "全局变量段起始: $GLOBAL_VAR_ADDR"

# 获取栈地址
STACK_START=$(sudo cat /proc/$PID/maps | grep "\[stack\]" | awk -F'-' '{print $1}')
echo "栈起始: $STACK_START"

# 计算页号（VPN）
VPN_GLOBAL=$((0x$GLOBAL_VAR_ADDR / 4096))
VPN_STACK=$((0x$STACK_START / 4096))

echo "全局变量 VPN: $VPN_GLOBAL (0x$(printf '%x' $VPN_GLOBAL))"
echo "栈 VPN: $VPN_STACK (0x$(printf '%x' $VPN_STACK))"

echo ""

# ========================================
# 步骤 5: 软件层页表属性分析
# ========================================
echo "=== 步骤 5: 软件层页表属性 (page-types) ==="
echo ""

echo "page-types 属性说明："
echo "  __R__ = referenced  (页被引用)"
echo "  __U__ = uptodate     (数据是最新的)"
echo "  __D__ = dirty         (页被修改，需写回)"
echo "  __l__ = lru           (在 LRU 缓存列表中)"
echo "  __A__ = active        (活跃页)"
echo "  __M__ = mmap          (内存映射)"
echo "  _Ma_b = anonymous swapbacked (匿名映射，可换出)"
echo ""

echo "查询全局变量段页表："
./page-types --pid $PID -a $VPN_GLOBAL 2>&1

echo ""
echo "查询栈页表（第一个页）："
./page-types --pid $PID -a $VPN_STACK 2>&1

echo ""

# ========================================
# 步骤 6: 解析 pagemap
# ========================================
echo "=== 步骤 6: 解析 pagemap (VA → PFN) ==="
echo ""

echo "pagemap 结构说明："
echo "  /proc/<pid>/pagemap 每条记录 64 位 (8 字节)"
echo "  Bits 0-54: PFN  (页帧号，物理页号)"
echo "  Bit 55-60: 保留"
echo "  Bit 61: swap/offset"
echo "  Bit 62: protnone (是否在交换文件中)"
echo "  Bit 63: present  (页面是否在内存中)"
echo ""

function parse_pagemap() {
    local pid=$1
    local va_hex=$2
    local va_name=$3

    local va_dec=$((0x$va_hex))
    local vpn=$((va_dec / 4096))
    local offset=$((va_dec % 4096))

    echo "--- $va_name (VA: $va_hex, VPN: $vpn, 页内偏移: $offset) ---"

    # 读取 pagemap 条目
    local pagemap_offset=$((vpn * 8))
    local entry_hex=$(sudo xxd -s $pagemap_offset -l 8 /proc/2>/dev/null | \
                      awk '{printf "0x%s%s%s%s%s", $8,$7,$6,$5,$4,$3,$2,$1}')

    echo "pagemap 条目: $entry_hex"

    # 解析位字段
    local entry_dec=$((0x$entry_hex))

    # Bit 63: present
    local present=$(( (entry_dec >> 63) & 1 ))
    # Bit 62: protnone (swap)
    local swap=$(( (entry_dec >> 62) & 1 ))
    # Bit 61: swap/offset
    local swap_offset=$(( (entry_dec >> 61) & 1 ))
    # PFN 是 bits 0-54
    local pfn=$((entry_dec & 0x7FFFFFFFFFFFFF ))

    echo "  Present (在内存中): $present"
    echo "  Swap (被换出): $swap"
    echo "  PFN: $pfn"

    if [ $present -eq 1 ]; then
        local pa=$((pfn * 4096 + offset))
        echo "  物理地址: 0x$(printf '%x' $pa) (PA=$pa)"
    else
        echo "  页面不在物理内存中 (PRESENT=0)"
        if [ $swap -eq 1 ]; then
            echo "  Swap offset: $pfn"
        fi
    fi
    echo ""
}

# 解析全局变量段第一个页
parse_pagemap $PID $GLOBAL_VAR_ADDR "全局变量页"

# 解析栈第一个页
parse_pagemap $PID $STACK_START "栈页"

echo ""

# ========================================
# 步骤 7: 查找硬件层 ARM PTE 属性
# ========================================
echo "=== 步骤 7: 软件层 ARM PTE 属性 ==="
echo ""

echo "ARM PTE 属性说明："
echo "  RW    = 可读可写"
echo "  RO    = 只读"
echo "  NX    = 不可执行 (No Execute)"
echo "  SHD   = 共享 (Shareable)"
echo "  AF    = 访问标志 (Access Flag)"
echo "  UXN   = 用户态不可执行 (User Execute Never)"
echo "  nGnRnE / nGnRE = 内存类型"
echo ""

echo "注意：/sys/kernel/debug/kernel_page_tables 默认只显示内核空间页表"
echo "用户态进程的 PTE 在进程私有的 mm_struct->pgd 中"
echo ""

echo "=== 内核页表中的 Linear Mapping (物理内存映射) ==="
sudo cat /sys/kernel/debug/kernel_page_tables 2>&1 | grep -A 2 "Linear Mapping start" | head -10

echo ""
echo "提示：要查看用户态特定地址的 ARM PTE，需要："
echo "  1. 从 pagemap 获取 PFN"
echo "  2. 在内核页表中搜索该物理地址对应的 PTE 条目"
echo "  3. 或者修改内核支持 per-process 页表 dump"
echo ""

# ========================================
# 步骤 8: 层级对比总结
# ========================================
echo "=== 步骤 8: 层级对比总结 ==="
echo ""

cat << 'EOF'
| 层级 | 来源 | 属性类型 | 示例 |
|--------|------|----------|------|
| 软件层 | page-types | Linux 内核 page flags | __RU_lA__M (referenced, uptodate, lru, active, mmap) |
| 软件层 | pagemap | VA → PFN 映射 | PFN + Present/Dirty/Swap 标志 |
| 硬件层 | kernel_page_tables | ARM 硬件 PTE | RW NX SHD AF UXN MEM/NORMAL |
|        |          | - R/W: 权限 |
|        |          | - NX: 可执行控制 |
|        |          | - AF: 访问标记 |
|        |          | - UXN: 用户态执行控制 |

关系：
  软件层 page-types 描述页面的缓存和 I/O 状态
  硬件层 PTE 描述硬件 MMU 如何处理该页面
  pagemap 连接虚拟地址和物理帧号
EOF

echo ""

# ========================================
# 步骤 9: 清理
# ========================================
echo "=== 清理 ==="
echo ""

echo "终止测试进程..."
kill $PID 2>/dev/null
wait $PID 2>/dev/null

echo "恢复 ASLR..."
echo 2 > /proc/sys/kernel/randomize_va_space
echo "ASLR 已恢复: $(cat /proc/sys/kernel/randomize_va_space)"

echo ""
echo "========================================"
echo "演示完成！"
echo "========================================"
