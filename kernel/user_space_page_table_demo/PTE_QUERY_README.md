# 用户态页表 PTE 属性查询工具

## 概述

`usr_pte_query` 是一个内核模块，用于查询用户态进程的页表属性。它直接读取 ARM64 硬件页表项（PTE），解析其中的属性字段。

## 功能特性

- 支持 4KB 页面映射查询
- 支持 2MB 大页（HugePage）映射查询
- 解析 ARM64 PTE 属性：
  - **AttrIdx**：内存类型索引（MEM/NORMAL、DEVICE/nGnRE 等）
  - **SH**：共享性属性（Inner/Outer Shareable、Non-shareable）
  - **Physical Address**：物理地址

## 与 stage1 ptdump 的解析一致性

本模块使用与内核 `arch/arm64/mm/ptdump.c` 完全相同的解析逻辑：

```c
prot = raw_pte & PTE_ATTRINDX_MASK;  // 提取 bits [4:2]
if (prot == PTE_ATTRINDX(MT_DEVICE_nGnRnE))
    return "DEVICE/nGnRnE";
if (prot == PTE_ATTRINDX(MT_NORMAL))
    return "MEM/NORMAL";
// ...
```

## AttrIdx 与内存类型映射

| AttrIdx 值 | MT_* 定义 | PTE_ATTRINDX 值 | 显示字符串 |
|-----------|-----------|-----------------|-----------|
| 0 | MT_NORMAL | 0x0 | MEM/NORMAL |
| 1 | MT_NORMAL_TAGGED | 0x4 | MEM/NORMAL-TAGGED |
| 2 | MT_NORMAL_NC | 0x8 | MEM/NORMAL-NC |
| 3 | MT_DEVICE_nGnRnE | 0xc | DEVICE/nGnRnE |
| 4 | MT_DEVICE_nGnRE | 0x10 | DEVICE/nGnRE |

## 编译

```bash
cd /mnt/kernel/user_space_page_table_demo/
make
```

编译产物：`usr_pte_query.ko`

## 使用方法

### 1. 启动测试程序

```bash
# 在一个终端启动 show_addr（会输出进程地址）
./show_addr &
# 记录输出的 PID

# 或者查看 show_addr 的内存映射
cat /proc/<pid>/maps | grep -E "\[heap\]|show_addr"
```

### 2. 加载模块查询页表属性

```bash
# 加载模块，指定 PID 和虚拟地址
insmod usr_pte_query.ko target_pid=<pid> target_va=0x<addr>

# 示例：查询堆地址
insmod usr_pte_query.ko target_pid=12345 target_va=0x421000

# 查询数据段地址
insmod usr_pte_query.ko target_pid=12345 target_va=0x420000
```

### 3. 查看输出

```bash
dmesg | tail -15
```

### 4. 卸载模块

```bash
rmmod usr_pte_query
```

## 输出示例

```
=========================================
usr_pte_query: PID=12345, VA=0x421000
=========================================
-----------------------------------------
PTE Level (4KB Page Mapping):
  Raw PTE:        0x00e80000a3717f43
  Physical Addr:  0x00080000a3717000
  AttrIdx:        MEM/NORMAL
  SH [9:8]:      3 (Inner Shareable)
-----------------------------------------
```

### 大页输出示例

```
=========================================
usr_pte_query: PID=12345, VA=0x40000000
=========================================
-----------------------------------------
PMD Level (2MB Block Mapping):
  Raw PMD:        0x00e80000a3717f43
  Physical Addr:  0x00080000a3717000
  AttrIdx:        MEM/NORMAL
  SH [9:8]:      3 (Inner Shareable)
-----------------------------------------
```

## 与 page-types 对比

| 工具 | 属性类型 | 来源 |
|------|---------|------|
| page-types | Linux 内核软件层 page flags | /proc/kpageflags |
| usr_pte_query | ARM64 硬件 PTE 属性 | 直接读取页表 |

page-types 显示的 `uptodate,lru,anonymous` 等标志描述的是页面在 Linux 内存管理中的状态，而我们的模块显示的是硬件 MMU 实际使用的内存类型属性。

## 验证结果

测试环境：openEuler ARM64

| 测试地址 | page-types 标志 | 模块 AttrIdx | 结论 |
|---------|----------------|-------------|------|
| Heap (0x421000) | uptodate,lru,mmap,anonymous | MEM/NORMAL | ✓ 匹配 |
| Data (0x420000) | uptodate,lru,mmap,anonymous | MEM/NORMAL | ✓ 匹配 |

## 注意事项

1. 需要 root 权限加载内核模块
2. 目标进程必须是用户态进程（内核线程没有 mm_struct）
3. 地址必须是页对齐的（4KB 或 2MB）
4. 仅支持 ARM64 架构

## 文件清单

```
usr_pte_query.c   # 内核模块源码
usr_pte_query.ko # 编译后的内核模块
Makefile         # 编译脚本
```
