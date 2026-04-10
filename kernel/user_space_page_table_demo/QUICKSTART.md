# 快速开始指南

## 一键运行演示

```bash
cd /mnt/kernel/user_space_page_table_demo
bash demo.sh
```

## 文件结构

```
/mnt/user_space_page_table_demo/
├── README.md                # 项目概述
├── SUMMARY.md               # 完整技术文档和流程说明
├── QUICKSTART.md            # 本文件 - 快速开始
├── show_addr.c             # 测试程序（C 代码）
├── demo.sh                  # 主测试脚本
└── page-types              # 页表分析工具（从内核编译）
```

## 演示流程图

```
用户态进程地址 (show_addr.c)
        │
        ├─ 全局变量 (DATA 段) ────> /proc/<pid>/pagemap ──> page-types ──> 软件页表属性
        │
        ├─ 局部变量 (STACK) ───────┼─ 页面未分配（PRESENT=0）
        │
        └─ 堆内存 (HEAP) ─────────┼─ PFN → 物理地址
                                           │
                                           └─> 内核页表搜索 → ARM PTE 属性
```

## 预期输出

### 1. 软件层页表属性 (page-types)

```
             flags    page-count       MB  symbolic-flags            long-symbolic-flags
0x0000000000005828            20        0  ___U_l_____Ma_b______________________________    uptodate,lru,mmap,anonymous,swapbacked
```

**关键标志说明：**
- `__R` = referenced（页被访问）
- `__U` = uptodate（数据最新）
- `__D` = dirty（页被修改）
- `__l` = lru（在缓存链表中）
- `__A` = active（活跃页）
- `__M` = mmap（内存映射）
- `_a_b` = anonymous, swapbacked（匿名映射，可换出）

### 2. pagemap 解析 (VA → PFN)

```
--- 全局变量页 (VA: 0x00420000, VPN: 1056, 页内偏移: 0) ---
pagemap 条目: 0x00000000 00007f40 00000000
  Present (在内存中): 1
  Swap (被换出): 0
  PFN: 0x7f40
  物理地址: 0x1fd00000 (PA=532440832)
```

**位字段说明：**
- **Bit 63 (present)**: 页面是否在物理内存中
- **Bit 62 (protnone)**: 页面是否被换出
- **Bit 61 (swap/offset)**: 交换偏移
- **Bits 0-54 (PFN)**: 页帧号（物理页号）

### 3. ARM PTE 属性说明

```
ARM PTE 属性说明：
  RW     = 可读可写
  RO     = 只读
  NX     = 不可执行
  SHD    = 共享
  AF     = 访问标志
  UXN    = 用户态不可执行
  nGnRnE / nGnRE = 内存类型
```

**重要提示：**
- `/sys/kernel/debug/kernel_page_tables` 默认只显示内核空间页表
- 用户态进程的 PTE 在进程私有的 `mm_struct->pgd` 中
- 要查看用户态的 ARM PTE，需通过 PFN 在内核页表中反查

## 故障排除

### 问题：stack 页面查询不到（total=0）

**原因：** 栈顶页面可能还没有被访问分配

**解决：** 在 `show_addr.c` 中主动访问栈地址

```c
int *stack_var;  // 在栈上
*stack_var = 42;    // 强制分配栈页面
```

### 问题：pagemap 读取全 0

**可能原因：**
1. 地址未在 `/proc/<pid>/maps` 中映射
2. 页面已被换出到交换分区（protnone=1）
3. 进程已退出

**验证方法：**
```bash
# 检查进程是否存在
ps -p $PID

# 查看完整的 maps
cat /proc/$PID/maps

# 手动验证地址
echo "0x<地址>" | xxd
```

## 手动分步测试

### 测试 1: 只运行程序，不查询

```bash
cd /mnt/user_space_page_table_demo
gcc -o show_addr show_addr.c
./show_addr  # 然后查看输出的地址
```

### 测试 2: 只使用 page-types 分析已运行的进程

```bash
# 获取一个正在运行的进程的 PID
PID=<运行的进程 PID>

# 查询所有页表
./page-types --pid $PID -l

# 查询特定地址范围
./page-types --pid $PID -a 0x1000,10
```

### 测试 3: 使用内核页表工具

```bash
# 查看内核空间页表
sudo cat /sys/kernel/debug/kernel_page_tables | head -50

# 搜索特定地址
sudo cat /sys/kernel/debug/kernel_page_tables | grep "0xffff"
```

## 下一步

1. **编写内核模块**：添加 per-process 页表 dump 接口
2. **使用 BPF**：在页表访问时捕获详细信息
3. **扩展 page-types**：添加 ARM PTE 属性显示功能
4. **集成到 CI**：自动验证内存布局和页表配置
