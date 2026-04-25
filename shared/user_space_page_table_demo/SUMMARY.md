# 用户态页表属性分析 - 完整流程总结

## 项目概述

本演示展示了如何获取和分析用户态进程的页表属性，包括：

1. **软件层页表属性**：使用 `page-types` 工具解析 `/proc/<pid>/pagemap`
2. **硬件层 ARM PTE 属性**：通过 PFN 在内核页表中反查
## 文件说明

- `show_addr.c`: 简单的 C 测试程序，输出变量地址
- `page-types`: 内核提供的页表分析工具（从内核源码编译）
- `demo.sh`: 整合的测试脚本，演示完整页表分析流程
- `README.md`: 项目说明
- `SUMMARY.md`: 输出结果和详细解释

## 快速开始

```bash
cd /mnt/user_space_page_table_demo
sh demo.sh
```

## 完整流程说明

### 步骤 1: 编译工具和测试程序

```bash
# 编译 page-types（已从内核源码编译完成）
# 编译测试程序
gcc -o show_addr show_addr.c
```

### 步骤 2: 准备测试环境

```bash
# 禁用 ASLR 获得稳定地址
echo 0 > /proc/sys/kernel/randomize_va_space

# 创建测试文件（用于 mmap 测试）
dd if=/dev/zero of=/tmp/demo_testfile bs=1K count=512
```

### 步骤 3: 启动测试程序

```bash
# 后台运行 show_addr
./show_addr &
PID=$!

# 输出信息：
# PID: <进程号>
# 全局变量地址: 0x...
# 局部变量地址: 0x...
# 堆内存地址: 0x...
```

### 步骤 4: 获取进程地址信息

```bash
# 查看 /proc/<pid>/maps 获取所有映射
cat /proc/$PID/maps

# 提取关键地址
GLOBAL_VAR_ADDR=$(cat /proc/$PID/maps | grep "rw-p 0001" | head -1 | cut -d'-' -f1)
STACK_START=$(cat /proc/$PID/maps | grep "\[stack\]" | cut -d'-' -f1)
HEAP_START=$(cat /proc/$PID/maps/ | grep "\[heap\]" | cut -d'-' -f1)

# 计算页号（VPN）和页内偏移
# VPN = VA / PAGE_SIZE  (PAGE_SIZE = 4096 字节)
# OFFSET = VA % PAGE_SIZE
VPN=$(( 0x$GLOBAL_VAR_ADDR / 4096 ))
OFFSET=$(( 0x$GLOBAL_VAR_ADDR % 4096 ))
```

### 步骤 5: 软件层页表属性分析

#### 方法 A: 使用 page-types 工具

```bash
# 查询特定页号
./page-types --pid $PID -a $VPN

# 输出格式：
# voffset offset len flags
# VPN      PFN    count attribute-flags long-flags-description

# 列出所有页面
./page-types --pid $PID -l

# 逐页显示
./page-types --pid $PID -L
```

**page-types 属性标志说明：**

| 标志 | 含义 |
|------|------|
| `__R` | referenced - 页被访问过 |
| `__U` | uptodate - 数据最新 |
| `__D` | dirty - 页被修改，需写回磁盘 |
| `__l` | lru - 在 LRU 缓存列表中 |
| `__A` | active - 活跃页 |
| `__M` | mmap - 内存映射 |
| `__L` | locked - 页被锁定 |
| `__W` | writeback - 正在写回 |
| `_Ma_b` | anonymous, swapbacked - 匿名映射，已被换出 |
| `__t` | thp - Transparent Huge Page |

#### 方法 B: 直接解析 /proc/<pid>/pagemap

```bash
# /proc/<pid>/pagemap 每条记录 64 位（8 字节）
# 格式：/proc/<pid>/pagemap
# 偏移为 VPN * 8 字节

# 读取特定虚拟页的 PFN
dd if=/proc/$PID/pagemap bs=8 count=1 skip=$VPN | od -A x -t u1

# 或使用 xxd
xxd -s $((VPN * 8)) -l 8 /proc/$PID/pagemap
```

**pagemap 条目位结构（小端序）：**

| 位范围 | 字段名称 | 说明 |
|--------|----------|------|
| 0-54 | PFN | 页帧号（物理页号） |
| 55-60 | 保留 | - |
| 61 | swap/offset | 交换偏移 |
| 62 | protnone | 是否在交换文件中（非物理内存） |
| 63 | present | 页面是否在物理内存中 |

```bash
# 解析示例
ENTRY_HEX="00000000 00000000 7f000000 00000000"
ENTRY_DEC=$((0x$ENTRY_HEX))

# 提取标志
PRESENT=$(( (ENTRY_DEC >> 63) & 1 ))  # 位 63
PROTNONE=$(( (ENTRY_DEC >> 62) & 1 ))  # 位 62
PFN=$(( ENTRY_DEC & 0x7FFFFFFFFFFFFF ))  # 位 0-54

if [ $PRESENT -eq 1 ]; then
    echo "页面在物理内存中"
    echo "PFN: $PFN"
    PA=$((PFN * 4096 + OFFSET))
    echo "物理地址: $PA"
else
    echo "页面不在物理内存中"
fi
```

### 步骤 6: 硬件层 ARM PTE 属性分析

**重要提示：** `/sys/kernel/debug/kernel_page_tables` 默认只显示内核空间（PID 0）的全局页表，不包括用户进程的页表。

#### 方法 A: 通过 PFN 在内核页表中查找

```bash
# 先从 pagemap 获取 PFN
PFN=$(从 pagemap 解析得到)

# 在内核页表中搜索该 PFN 对应的 PTE
# 物理地址 = PFN * 4096
PA=$((PFN * 4096))

# 搜索内核页表
cat /sys/kernel/debug/kernel_page_tables | grep -A 5 -B 5 "$PA"
```

#### 方法 B: 使用 gdb 调试内核

```bash
# 需要加载符号的内核 vmlinux
gdb vmlinux

# 连接到正在运行的进程
(gdb) attach <PID>

# 查看进程的 mm_struct
(gdb) p *current->mm

# 查看页表基址
(gdb) p current->mm->pgd
```

#### 方法 C: 修改内核支持 per-process dump（高级）

需要修改内核代码添加 per-process 页表 dump 接口，类似：

```c
// 在 /proc/<pid>/ 下添加 page_table 文件
// 该文件输出当前进程的完整页表信息，包括：
// - 每个 PGD/PUD/PMD/PTE 的内容
// - ARM PTE 属性：RW, RO, NX, SHD, AF, UXN, 类型等
```

**ARM PTE 属性说明（硬件级）：**

| 标志 | 含义 |
|------|------|
| `RW` | 可读可写 |
| `RO` | 只读 |
| `NX` | 不可执行（No Execute） |
| `SHD` | 共享（Shareable） |
| `AF` | 访问标志（Access Flag） |
| `UXN` | 用户态不可执行（User Execute Never） |
| `nG` | 普通（Normal）内存 |
| `nR` / `nE` | 设备内存类型 |

## 页表属性层级对比

```
┌──────────┬──────────┬──────────────────────┬──────────────────────────────────────────┐
│  层级   │  来源    │ 属性类型         │ 示例                                    │
├──────────┼──────────┼──────────────────────┼──────────────────────────────────────────┤
│ 软件层  │ page-types │ Linux 内核 page  │ __RU_lA____M (referenced,       │
│          │          │ flags             │ uptodate, lru, active, mmap)          │
├──────────┼──────────┼──────────────────────┼──────────────────────────────────────────┤
│ 软件层  │ pagemap  │ VA → PFN 映射    │ PFN + Present/Dirty/Swap 标志          │
├──────────┼──────────┼──────────────────────┼──────────────────────────────────────────┤
│ 硬件层  │ kernel_pt│ ARM 硬件 PTE     │ RW NX SHD AF UXN MEM/NORMAL            │
│          │          │                   │ - R/W: 权限                             │
│          │          │                   │ - NX: 可执行控制                         │
│          │          │                   │ - AF: 访问标记                           │
│          │          │                   │ - UXN: 用户态执行控制                     │
└──────────┴──────────┴──────────────────────┴──────────────────────────────────────────┘
```

## 关键概念说明

### 1. 虚拟地址空间布局（ARM64，48 位）

```
0x0000_0000_0000 - 0x0000_ffff_ffff_f000  用户空间（47 位）
0xffff_0000_0000 - 0xffff_ffff_ffff_f000  内核空间（47 位）
                              ^^^^^^48 位内核空间基址

用户空间细分：
- 0x0000... - 0x00...ffff:  TEXT 段（代码）
- 0x00... - 0x00...:     DATA 段（全局变量）
- [heap]: 堆内存
- [stack]: 栈内存
- ... (加载的共享库)
```

### 2. 页表层级结构（ARM64）

```
虚拟地址 (VA)
    ↓
PGD (Page Global Directory, 4 级)
    ↓
PUD (Page Upper Directory, 3 级)
    ↓
PMD (Page Middle Directory, 2 级)
    ↓
PTE (Page Table Entry, 1 级)
    ↓
物理页帧 (PFN) + 偏移
```

### 3. 页面大小和地址计算

```bash
PAGE_SIZE=4096  # 4 KB（标准页大小）

# 虚拟页号（VPN）
VPN = VA / PAGE_SIZE

# 页内偏移
OFFSET = VA % PAGE_SIZE

# 物理地址（通过 PFN）
PA = PFN * PAGE_SIZE + OFFSET
```

### 4. ASLR 对地址的影响

```bash
# ASLR (Address Space Layout Randomization)
# 0 = 关闭（地址固定，方便调试）
# 1 = 部分随机化（栈、mmap、库基址随机）
# 2 = 完全随机化（包括堆）

# 测试时应禁用 ASLR：
echo 0 > /proc/sys/kernel/randomize_va_space
```

## 常见问题和解决方案

### Q1: 为什么 stack 地址查询不到页表属性？

**A:** 栈顶页面可能还没有被访问，不存在物理内存中。

```bash
# 检查 pagemap 条目
# 如果全是 0，说明 PAGE 未分配（PRESENT=0）

# 解决方案：在程序中主动访问该地址
int *stack_var = ...;  // 强制分配栈变量
*stack_var = 42;         // 触发页错误
```

### Q2: 为什么 page-types 输出 total=0？

**A:** 可能是地址超出了当前进程的映射范围，或 VPN 计算错误。

```bash
# 验证地址是否在 maps 中
VA=0x...
cat /proc/$PID/maps | grep $VA

# 验证 VPN 计算
VPN=$(( 0x$VA / 4096 ))
echo "VPN: 0x$(printf '%x' $VPN)"
```

### Q3: /sys/kernel/debug/kernel_page_tables 看不到用户进程的页表？

**A:** 这是设计限制。该文件只 dump 内核进程（PID 0）的页表。

**解决方案：**
1. 使用 pagemap + page-types 分析用户空间
2. 修改内核添加 per-process dump 接口
3. 使用 perf、bpftrace 等工具

### Q4: page-types 显示的属性和 ARM PTE 不一样？

**A:** 它们表示不同层次：

| 工具 | 层次 | 说明 |
|------|------|------|
| page-types | 操作系统 | 缓存策略、I/O 状态、页的生命周期 |
| ARM PTE | 硬件 MMU | CPU 如何处理该页面（权限、可执行性） |

## 扩展建议

1. **编写内核模块**：创建一个 `/proc/<pid>/page_table_dump` 文件，输出完整用户态页表
2. **使用 BPF**：编写 eBPF 程序在页表访问时捕获信息
3. **使用 perf**：`perf record -e page-faults` 分析缺页异常
4. **集成到自动化测试**：将此流程集成到 CI/CD 流程中

## 参考资料

- Linux 内核文档：`Documentation/admin-guide/mm/pagemap.rst`
- ARM64 架构手册：ARMv8-A 架构参考手册
- `page-types` 源码：`tools/mm/page-types.c`
- 内核调试 FS：`CONFIG_PTDUMP_DEBUGFS`
