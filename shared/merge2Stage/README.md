# Stage-2 Page Table Dump Patches 分析

这五个 patch 实现了 KVM arm64 的 stage-2 页面表导出功能，允许用户空间通过 debugfs 查看 guest VM 的 stage-2 页表内容。

---

## ⚠️ 重要警告

**`stage2_page_tables` 操作有风险，可能导致 VM 崩溃或重启！**

原因：该功能需要持有 `kvm->mmu_lock` 锁来 walk 页表，对于繁忙或大型 VM，锁持有时间可能过长，触发：
- Watchdog timeout
- panic 机制
- VM 整个重启

**建议：**
1. **不要在生产环境**对正在高负载运行的 VM 使用此功能
2. 优先使用其他间接方式排查问题（见下方替代方案）
3. 如必须使用，先暂停 VM 再操作

---

## Patch 1: Move pagetable definitions to common header

**文件变更：**
- `arch/arm64/include/asm/kvm_pgtable.h` (+35 行)
- `arch/arm64/kvm/hyp/pgtable.c` (-44 行)

**作用：**

将 KVM 页面表相关的宏定义从 `pgtable.c` 移到公共头文件 `kvm_pgtable.h`，使其可以被其他文件复用。

**移动的宏定义：**
```c
#define KVM_PTE_LEAF_ATTR_LO          GENMASK(11, 2)
#define KVM_PTE_LEAF_ATTR_LO_S1_ATTRIDX  GENMASK(4, 2)
#define KVM_PTE_LEAF_ATTR_LO_S1_AP      GENMASK(7, 6)
#define KVM_PTE_LEAF_ATTR_LO_S1_SH      GENMASK(9, 8)
#define KVM_PTE_LEAF_ATTR_LO_S1_AF      BIT(10)
#define KVM_PTE_LEAF_ATTR_LO_S2_MEMATTR GENMASK(5, 2)
#define KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R  BIT(6)
#define KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W  BIT(7)
// ... 等等
```

这些宏定义了 stage-1 和 stage-2 页表条目的属性位布局，是后续 stage-2 ptdump 的基础。

---

## Patch 2: Expose the attribute parsing functionality

**文件变更：**
- `arch/arm64/include/asm/ptdump.h` (+43 行)
- `arch/arm64/mm/ptdump.c` (-45 行)

**作用：**

将 ptdump（page table dump）的核心数据结构和解析函数暴露到公共头文件，供 stage-2 ptdump 复用。

**新增的结构体：**

```c
// 属性位描述
struct ptdump_prot_bits {
    u64      mask;
    u64      val;
    const char *set;
    const char *clear;
};

// 页面层级描述
struct ptdump_pg_level {
    const struct ptdump_prot_bits *bits;
    const char *name;
    size_t num;
    u64 mask;
};

// 解析状态
struct ptdump_pg_state {
    struct ptdump_state ptdump;
    struct seq_file *seq;
    const struct addr_marker *marker;
    const struct mm_struct *mm;
    unsigned long start_address;
    int level;
    u64 current_prot;
    bool check_wx;
    unsigned long wx_pages;
    unsigned long uxn_pages;
};
```

**关键改动：**
- `note_page()` 函数从 `static` 改为公开，可被外部调用
- 添加了 `#else` 分支提供空实现，避免未启用 CONFIG_PTDUMP_CORE 时编译失败

---

## Patch 3: Use the ptdump description from a local context

**文件变更：**
- `arch/arm64/include/asm/ptdump.h` (+1 行)
- `arch/arm64/mm/ptdump.c` (+10/-5 行)

**作用：**

允许 ptdump 调用者使用自定义的页面层级描述数组，而非使用全局的 `pg_level[]`。

**核心改动：**

在 `struct ptdump_pg_state` 中添加指针：
```c
struct ptdump_pg_state {
    struct ptdump_state ptdump;
    struct ptdump_pg_level *pg_level;  // 新增：指向本地描述数组
    // ... 其他字段
};
```

将 `pg_level[]` 重命名为 `kernel_pg_levels[]`，并在 `note_page()` 中通过 `st->pg_level` 访问。

**设计意图：**
- stage-2 页表的属性位布局与 stage-1 不同（使用 S2AP、XN 等）
- 通过这个指针机制，stage-2 ptdump 可以使用自己的描述数组

---

## Patch 4: Don't override the level when operating on stage-2 tables

**文件变更：**
- `arch/arm64/mm/ptdump.c` (+5 行)

**作用：**

防止在 stage-2 页表操作时错误覆盖 level 值。

**问题背景：**

原始代码中，`note_page()` 会根据 `mm_p4d_folded()` 和 `mm_pud_folded()` 动态调整 level（将折叠的层级设为 0）。但 stage-2 ptdump 不使用 `mm` 参数，导致这些检查可能产生错误结果。

**修复代码：**
```c
/* check if the current level has been folded dynamically */
if (st->mm && ((level == 1 && mm_p4d_folded(st->mm)) ||
               (level == 2 && mm_pud_folded(st->mm))))
    level = 0;
```

通过 `st->mm` 检查来区分：如果是 stage-2 操作（`mm == NULL`），则跳过 folded 层级调整。

---

## Patch 5: Register ptdump with debugfs on guest creation

**文件变更：**
- `arch/arm64/include/asm/kvm_mmu.h` (+7 行)
- `arch/arm64/kvm/Kconfig` (+17 行)
- `arch/arm64/kvm/Makefile` (+1 行)
- `arch/arm64/kvm/arm.c` (+8 行)
- `arch/arm64/kvm/ptdump.c` (新文件，+268 行)

**作用：**

在 KVM guest 创建时，通过 debugfs 注册 stage-2 页表导出功能。

**新增配置选项：**
```kconfig
config PTDUMP_STAGE2_DEBUGFS
    bool "Present the stage-2 pagetables to debugfs"
    depends on KVM
    depends on DEBUG_KERNEL
    depends on DEBUG_FS
    depends on GENERIC_PTDUMP
    select PTDUMP_CORE
    default n
```

**debugfs 创建的文件：**

当 guest 创建后，在 `$GUEST_DEBUGFS_DIR/` 下生成三个文件：

| 文件名 | 作用 |
|--------|------|
| `stage2_page_tables` | 显示 guest stage-2 页表内容和权限 |
| `ipa_range` | 显示 IPA（Intermediate Physical Address）范围 |
| `stage2_levels` | 显示页表级数 |

**stage2_pte_bits 定义：**
```c
static const struct ptdump_prot_bits stage2_pte_bits[] = {
    { mask = PTE_VALID, val = PTE_VALID, .set = " ", .clear = "F" },
    { mask = KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R | PTE_VALID, .set = "R", .clear = " " },
    { mask = KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W | PTE_VALID, .set = "W", .clear = " " },
    { mask = KVM_PTE_LEAF_ATTR_HI_S2_XN | PTE_VALID, .set = " ", .clear = "X" },
    { mask = KVM_PTE_LEAF_ATTR_LO_S2_AF | PTE_VALID, .set = "AF", .clear = "  " },
    { mask = PTE_TABLE_BIT | PTE_VALID, .set = "BLK", .clear = "   " },
};
```

这定义了 stage-2 页表条目的属性位显示格式，与 stage-1 的显示格式不同。

---

## 整体架构

```
用户空间
    │
    ▼
debugfs (/sys/kernel/debug/kvm/<vm_id>/)
    │
    ├── stage2_page_tables  ──► kvm_ptdump_guest_show()
    │                              │
    │                              ▼
    │                         kvm_pgtable_walk()
    │                              │
    │                              ▼
    │                         note_page() ◄─── ptdump_pg_state
    │                              │
    │                              ▼
    │                         dump_prot() ◄─── stage2_pte_bits (自定义描述)
    │
    ├── ipa_range
    └── stage2_levels
```

**关键设计点：**

1. **代码复用**：Patch 1-3 将基础设施移到公共头文件，供 stage-2 ptdump 复用
2. **灵活描述**：通过 `pg_level` 指针机制，支持 stage-2 使用自己的属性位描述
3. **安全检查**：通过 `st->mm` 检查区分 stage-1 和 stage-2 操作
4. **统一接口**：`note_page()` 作为核心解析函数，被 stage-1 和 stage-2 共同使用

---

## 使用说明

### 前提条件

内核需要启用以下配置选项：

**Stage-1（Kernel Page Tables）：**
```bash
CONFIG_DEBUG_WX=y          # 启用 W+X 检查（会自动选中 PTDUMP_CORE）
CONFIG_PTDUMP_CORE=y
CONFIG_PTDUMP_DEBUGFS=y     # 可选，需要 DEBUG_FS
```

**Stage-2（Guest Stage-2 Page Tables）：**
```bash
CONFIG_PTDUMP_STAGE2_DEBUGFS=y
```

可通过以下命令检查当前配置：
```bash
grep -E "CONFIG_DEBUG_WX|CONFIG_PTDUMP" /boot/config-$(uname -r)
```

---

### Stage-1: 查看 Host Kernel 页表

Stage-1 ptdump 用于查看 Host 内核的页表布局，检测 W+X（Writable + Executable）映射等安全问题。

**1. 确保 debugfs 已挂载：**
```bash
mount -t debugfs debugfs /sys/kernel/debug
```

**2. 查看页表文件：**
```bash
# 查看所有 kernel 页表
cat /sys/kernel/debug/kernel_page_tables

# 或者通过 debugfs 目录
ls -la /sys/kernel/debug/kernel_page_tables
```

**3. 输出示例：**
```
---[ Linear Mapping start ]---
0x0000004000000000-0x0000008000000000   17179869184GB     PGD
    R……
---[ Linear Mapping end ]---
---[ vmalloc() area ]---
0xffffff8000000000-0xffffffc000000000   17179869184GB     PGD
......
```

**4. 权限标志说明：**
| 标志 | 含义 |
|------|------|
| `ro` | Read-only |
| `RW` | Read-Write（未设置 ro） |
| `NX` | No-Execute |
| `x ` | Executable（未设置 NX） |
| `AF` | Accessed Flag |
| `NG` | Not Global |
| `SHD` | Shared |
| `CON` | Contiguous |
| `GP` | Global Profile |

**5. 启动时自动检查 W+X：**

如果启用了 `CONFIG_DEBUG_WX`，内核启动时会自动检查并报告 W+X 映射：
```
[    0.000000] arm64: Checked W+X mappings: passed, no W+X pages found
```
或检查失败时：
```
[    0.000000] arm64: Checked W+X mappings: FAILED, 5 W+X pages found
```

---

### Stage-2: 查看 Guest Stage-2 页表

Stage-2 ptdump 用于查看 KVM guest 的 stage-2 页表，需要 guest 处于运行状态。

**1. 前提条件：**
- 内核已启用 `CONFIG_PTDUMP_STAGE2_DEBUGFS`
- 有正在运行的 KVM guest

**2. 查看 debugfs 目录结构：**
```bash
ls -la /sys/kernel/debug/kvm/
```

**3. 启动一个 guest 后，查看其 debugfs 目录：**

每个运行的 guest 在 `/sys/kernel/debug/kvm/` 下有一个以 VM ID 命名的目录：
```bash
ls -la /sys/kernel/debug/kvm/
# dr-xr-x--- 1 root root guest-vm-0/
# dr-xr-x--- 1 root root guest-vm-1/
```

**4. 查看特定 Guest 的 Stage-2 页表：**

```bash
# 查看该 guest 的 stage-2 页表内容
cat /sys/kernel/debug/kvm/<vm_id>/stage2_page_tables

# 示例：假设 guest VM ID 为 0
cat /sys/kernel/debug/kvm/0/stage2_page_tables
```

**5. 输出示例：**
```
---[ Guest IPA ]---
0x0000000000000000-0x0000000000400000      4194304     PGD
0x0000000000400000-0x0000000040000000   1073741824     PGD
    R W  AF
0x0000000040000000-0x0000004000000000      4194304     PGD
```

**6. 查看 IPA 范围：**
```bash
cat /sys/kernel/debug/kvm/<vm_id>/ipa_range
# 输出示例：48  （表示 IPA 范围为 2^48）
```

**7. 查看页表级数：**
```bash
cat /sys/kernel/debug/kvm/<vm_id>/stage2_levels
# 输出示例：4  （表示 4 级页表）
```

**Stage-2 权限标志说明：**
| 标志 | 含义 |
|------|------|
| ` ` (空格) | Valid 且无特殊属性 |
| `F` | Fault/Invalid |
| `R` | Readable（S2AP_R） |
| `W` | Writable（S2AP_W） |
| `X` | Execute 禁用（XN） |
| `AF` | Accessed Flag |
| `BLK` | Block 映射（非 Page） |

---

### 常见使用场景

**场景 1：排查 Guest 内存映射问题**

```bash
# 1. 确认 guest 在运行
virsh list

# 2. 获取 guest 的 VM ID（通常为 0, 1, 2...）
# 或者通过 ps 查看 kvm 进程

# 3. 查看其 stage-2 页表
cat /sys/kernel/debug/kvm/0/stage2_page_tables | head -100
```

**场景 2：检查 W+X 映射（Host）**

```bash
# 启动时检查日志
dmesg | grep "W+X"

# 或直接查看页表
cat /sys/kernel/debug/kernel_page_tables | grep -E "RW.*NX|RW.* "
```

**场景 3：验证 Guest 内存布局**

```bash
# 在 guest 内部查看内存布局
cat /proc/iomem

# 在 host 查看对应的 stage-2 映射
cat /sys/kernel/debug/kvm/<vm_id>/stage2_page_tables | grep <address>
```

---

### 注意事项

1. **性能影响**：Stage-2 页表 walk 需要获取 `kvm->mmu_lock` 锁，大型 guest 可能会有性能开销
2. **安全考量**：Stage-2 页表暴露了 guest 的内存布局信息，仅应在调试环境使用
3. **需要 root 权限**：debugfs 目录通常需要 root 权限访问
4. **Guest 状态**：部分信息可能只在 guest 运行时才有意义（如 IPA 范围）

---

## 实战案例：MLX5 MMIO 性能问题排查

### 问题描述

使用 id_read_lat 测试 mlx5_0，发现 **Host 作为 server、Guest 作为 client 时，Guest 中 `post_send_db` 的 MMIO 写操作性能显著差于 Host 作为 client**。

**关键代码（mlx5 驱动）：**
```c
static inline void post_send_db(struct mlx5_qp *qp, struct mlx5_bf *bf,
                int nreq, int inl, int size, void *ctrl)
{
    // bf->reg 是 MMIO 寄存器地址
    mmio_write64_be(bf->reg + bf->offset, *(__be64 *)ctrl);
}
```

**核心差异：**
| 测试场景 | 页表层数 | MMIO 地址转换 |
|----------|----------|---------------|
| Host 作为 client | 1 层（stage1） | GVA → PA |
| Guest 作为 client | 2 层（stage1 + stage2） | GVA → GPA → HPA |

### 实验方案

#### 整体思路

通过对比 Host 和 Guest 中 MMIO 区域的页表属性，找出可能导致性能差异的原因。核心是：
1. 在用户态测试代码中打印 `bf->reg` 的地址
2. 在 Host/Guest 中分别获取该地址对应的页表属性
3. 对比两端的 Memory Type 属性（MemAttr）

#### 调试代码添加

在 mlx5 rdma 测试工具（id_read_lat/ib_write_lat）的用户态代码中添加地址打印：

```c
// 在调用 post_send_db 之前添加
printf("DEBUG: bf->reg = %p, offset = %d, total = %p\n",
       bf->reg, bf->offset, bf->reg + bf->offset);
```

这个地址就是 MMIO 区域的虚拟地址（GVA in guest, or kernel VA on host）。

### Part A: Host 作为 Client（获取基准数据）

**1. 确认 mlx5 设备的 BAR 地址范围：**
```bash
# 查找 mlx5 设备的 BAR 地址
lspci -vv -s $(lspci | grep mlx5 | awk '{print $1}')

# 或通过 sysfs
cat /sys/bus/pci/devices/0000\:03\:00.0/resource2
```

**2. 查看 Host 侧页表属性：**
```bash
# 确认 debugfs 已挂载
mount -t debugfs debugfs /sys/kernel/debug

# 使用 ptdump 查看 host 侧页表
cat /sys/kernel/debug/kernel_page_tables | grep <mmio_phys_addr>
```

**3. 记录基准数据：**
- MMIO 物理地址
- Memory Type 属性（如 `MEM/NORMAL` 或 `DEVICE/nGnRE`）
- 页面大小（4K/2M）

### Part B: Guest 作为 Client（待排查）

**1. 在 Guest 中运行测试，打印 bf->reg 的 GVA：**
```
DEBUG: bf->reg = 0x8000000000, offset = 0, total = 0x8000000000
```

**2. GVA → GPA 转换（使用 pagemap）：**
```bash
# 读取 /proc/<pid>/maps 确认地址属于哪个映射
cat /proc/$(pgrep -f "id_read_lat|ib_write_lat")/maps | grep -i mlx5

# 使用 pagemap 将 GVA 转换为 GPA
# pagemap 每行 8 字节表示一个虚拟页
OFFSET=$((<vaddr> / 4096 * 8))
dd if=/proc/$(pgrep -f "id_read_lat")/pagemap bs=8 skip=$((OFFSET/8)) count=1 2>/dev/null | xxd

# PFN = (pagemap_value & 0x7fffffffffffff) >> 12
# GPA = PFN * PAGE_SIZE + offset_in_page
```

或者写一个小工具自动做这个转换：
```c
// gva_to_gpa.c
unsigned long vaddr = strtoul(argv[1], NULL, 16);
FILE *f = fopen("/proc/self/pagemap", "rb");
fseek(f, (vaddr / PAGE_SIZE) * 8, SEEK_SET);
unsigned long pagemap_val;
fread(&pagemap_val, 8, 1, f);
unsigned long pfn = (pagemap_val & 0x7fffffffffffff) >> 12;
unsigned long gpa = (pfn * PAGE_SIZE) | (vaddr & (PAGE_SIZE - 1));
printf("GPA: 0x%lx\n", gpa);
```

**3. 在 Host 上用 GPA 查询 Stage2 页表：**
```bash
# 找到 VM 的 debugfs 目录
VM_PID=$(ps aux | grep "qemu\|kvm" | grep -v grep | awk '{print $2}' | head -1)
GUEST_DEBUGFS="/sys/kernel/debug/kvm/kvm-${VM_PID}"

# 列出可用的 debugfs 文件
ls -la ${GUEST_DEBUGFS}/

# 查看 stage2 页表
cat ${GUEST_DEBUGFS}/stage2_page_tables

# 用 grep 过滤 GPA 附近范围
cat ${GUEST_DEBUGFS}/stage2_page_tables | grep -A5 -B5 "0x..."
```

**注意**: GPA 应该匹配 mlx5 BAR2 的地址范围（通常在 2GB-16GB 区域）。


### 对比分析

#### 数据汇总表

| 指标 | Host (client) | Guest (client) |
|------|---------------|-----------------|
| write_addr GVA | `0x6000000000` | `0x8000000000` |
| PA/GPA | PA = `0x21c00000` | GPA = `0x8000000000`（通过 pagemap） |
| Stage-1 页表索引 | VA | VA（GVA） |
| Stage-2 页表索引 | N/A | GPA |
| Stage-1 页表 | Host debugfs 查 | Guest debugfs 查 |
| Stage-2 页表 | 无 | Host debugfs 查 |
| 页面大小 | 4K / 2M | 4K / 2M |
| R/W/AF/XN 属性 | | |

#### 可能根因分析

**关键怀疑**: Guest 的 MMIO 区域如果被 VFIO/IOMMU 映射时设置为 `Device_nGnRE`，而 Host 侧是 `Normal_Cacheable`，会导致写合并（Write Combining）被禁用，每次 MMIO 写都需要从 device 确认完成，从而显著增加延时。

**MemAttr 值参考（arm64 Stage-2）：**
| MemAttr 值 | 含义 | 性能特性 |
|-----------|------|---------|
| `MT_S2_NORMAL` (0xf) | Normal Cacheable | 高速，支持写合并 |
| `MT_S2_DEVICE_nGnRE` (0x1) | Device, nGnRE | 低速，无写合并 |
| `MT_S2_FWB_NORMAL` (6) | Normal with Forwarding Blocker | 中速 |

**如果 Guest 的 MMIO 被设为 Device_nGnRE 而 Host 是 Normal_Cacheable**，这就是延时差异的原因。

**Stage-2 页表 MemAttr 显示修复**：

当前 ptdump 的 `stage2_page_tables` 输出不包含 MemAttr 属性。需要在 `arch/arm64/kvm/ptdump.c` 中添加：

```c
// 在 stage2_pte_bits[] 中添加 MemAttr 条目
{
    .mask   = KVM_PTE_LEAF_ATTR_LO_S2_MEMATTR,
    .val    = PTE_S2_MEMATTR(MT_S2_NORMAL),
    .set    = "NORMAL",
}, {
    .mask   = KVM_PTE_LEAF_ATTR_LO_S2_MEMATTR,
    .val    = PTE_S2_MEMATTR(MT_S2_DEVICE_nGnRE),
    .set    = "DEVnGnRE",
}, {
    .mask   = KVM_PTE_LEAF_ATTR_LO_S2_MEMATTR,
    .val    = PTE_S2_MEMATTR(MT_S2_FWB_NORMAL),
    .set    = "NORMAL_FWB",
},
```


#### Stage-1 / Stage-2 PTE 属性含义

| 属性 | 含义 |
|------|------|
| `R` | Read 权限（S2AP_R for stage-2） |
| `W` | Write 权限（S2AP_W for stage-2） |
| `AF` | Accessed Flag |
| `XN` | Execute Never |
| `BLK` | Block 映射（2M/1G），非 4K page |
| `F` | Fault - 页表项无效 |
| `NORMAL` | Normal Cacheable Memory（高速） |
| `DEVnGnRE` | Device Memory, nGnRE（低速，无写合并） |
| `NORMAL_FWB` | Normal with Forwarding Blocker |

#### 关键检查点

- [ ] Guest 的 MMIO GVA 是否在 stage2 中正确映射（不是 `F`=Fault）
- [ ] MemAttr 是否为 `NORMAL`（高速路径）还是 `DEVnGnRE`（低速路径）
- [ ] Host 侧的 Memory Type 是什么？（从 `kernel_page_tables` 查看）
- [ ] 映射的页面大小是否与 Host 一致（2M vs 4K）
- [ ] Guest stage-1 和 stage-2 的属性是否一致

---

## OpenEuler Kernel 编译步骤（适用于虚拟化环境）

### 1. 查看 OS 版本
```bash
cat /etc/os-release
# 输出: openEuler 24.03 (LTS)
```

### 2. 确认系统环境
```bash
uname -r                    # 查看当前内核版本: 6.6.0-28.0.0.34.oe2403.aarch64
arch                        # 确认架构（aarch64）
nproc                       # 查看可用 CPU 核心数（示例：8）
```

### 3. 备份并恢复被修改的文件
如果编译时报错 `implicit declaration of function 'kvm_compute_layout'`，说明 KVM 相关文件被意外修改。检查并恢复：
```bash
git status --short
# 如果有文件被修改（如 arch/arm64/kvm/Kconfig, arch/arm64/include/asm/kvm_mmu.h 等）

# 恢复所有被修改的 KVM/ARM64 文件
git checkout arch/arm64/kvm/Kconfig \
             arch/arm64/include/asm/kvm_mmu.h \
             arch/arm64/include/asm/kvm_pgtable.h \
             arch/arm64/include/asm/ptdump.h \
             arch/arm64/kvm/Makefile \
             arch/arm64/kvm/arm.c \
             arch/arm64/kvm/hyp/pgtable.c \
             arch/arm64/mm/ptdump.c
```

### 4. 复制现有配置并更新
```bash
# 复制当前启动内核的配置作为基础
cp /boot/config-$(uname -r) .config

# 清理源码树（如果之前有编译残留）
make mrproper

# 恢复配置
cp /boot/config-$(uname -r) .config

# 自动设置新选项的默认值
make olddefconfig
```

### 5. 启用虚拟化支持
```bash
# 启用虚拟化基础框架
scripts/config --enable CONFIG_VIRTUALIZATION

# 启用 KVM 虚拟机管理程序
scripts/config --enable CONFIG_KVM

# 启用 virtio 驱动
scripts/config --enable CONFIG_VIRT_DRIVERS

# 重新应用配置
make olddefconfig
```

### 6. 解决证书缺失问题（可选）
如果遇到 `No rule to make target 'certs/openeuler-cert.pem'` 错误：
```bash
scripts/config --disable CONFIG_SYSTEM_TRUSTED_KEYS
scripts/config --disable CONFIG_SYSTEM_EXTRA_CERTIFICATE
make olddefconfig
```

### 7. 编译内核镜像
```bash
# 编译 ARM64 内核镜像（使用所有 CPU 核心加速）
make -j$(nproc) Image

# 验证生成的镜像
ls -lh arch/arm64/boot/Image
# 输出示例: -rw-r--r-- 1 root root 36M Apr  2 16:32 arch/arm64/boot/Image
```

### 8. 编译内核模块
```bash
make -j$(nproc) modules
```

### 9. 验证虚拟化配置
```bash
grep -E "CONFIG_VIRTUALIZATION|CONFIG_KVM" .config
# 应显示:
# CONFIG_VIRTUALIZATION=y
# CONFIG_KVM=y
# CONFIG_KVM_MMIO=y
# CONFIG_KVM_VFIO=y
# CONFIG_KVM_GENERIC_DIRTYLOG_READ_PROTECT=y
# CONFIG_VIRT_DRIVERS=y
```

### 10. 安装内核模块
```bash
make modules_install
# 模块将安装到 /lib/modules/6.6.0+/
```

### 11. 安装内核到 /boot
```bash
# 复制内核镜像和 System.map 到 /boot
/bin/cp -f arch/arm64/boot/Image /boot/vmlinuz-6.6.0+
/bin/cp -f System.map /boot/System.map-6.6.0+

# 验证
ls -lh /boot/vmlinuz-6.6.0+ /boot/System.map-6.6.0+
```

### 12. 更新引导程序
```bash
# 生成新的 grub 配置
grub2-mkconfig -o /boot/grub2/grub.cfg

# 验证新内核条目已添加
grep -A5 "vmlinuz-6.6.0+" /boot/grub2/grub.cfg
```

### 13. 重启系统
```bash
reboot
```

### 14. 重启后验证
```bash
# 选择新内核启动后，运行以下命令验证：

# 确认内核版本
uname -r
# 应显示: 6.6.0+

# 检查 KVM 模块是否加载
lsmod | grep kvm
# 应显示 kvm 模块

# 检查虚拟化功能
dmesg | grep -i kvm

# 检查 CPU 虚拟化特性
cat /proc/cpuinfo | grep -i virt
```

### 关键配置项说明

| 配置项 | 说明 |
|--------|------|
| `CONFIG_VIRTUALIZATION=y` | 启用虚拟化基础框架 |
| `CONFIG_KVM=y` | 启用 KVM 虚拟机管理程序 |
| `CONFIG_KVM_ARM_HOST=y` | 启用 ARM64 Host 支持（如果可用） |
| `CONFIG_VIRT_DRIVERS=y` | 启用 virtio 驱动 |
| `CONFIG_KVM_MMIO=y` | KVM MMIO 设备支持 |
| `CONFIG_KVM_VFIO=y` | KVM VFIO 设备支持 |

### 常见问题

**Q: 编译时提示 `implicit declaration of function 'kvm_compute_layout'`**
A: KVM 头文件被修改。执行步骤 3 恢复所有被修改的文件。

**Q: 编译时提示 `No rule to make target 'certs/openeuler-cert.pem'`**
A: 执行步骤 6 禁用系统信任密钥配置。

**Q: 如何选择启动新内核？**
A: 重启后在 grub 菜单中选择 `openEuler` -> `Linux (6.6.0+)`。

**Q: 如何确认编译出的内核支持虚拟化？**
A: 重启后运行 `lsmod | grep kvm`，应该看到 `kvm` 模块。

### 3. 复制现有配置并更新
```bash
# 复制当前启动内核的配置作为基础
cp /boot/config-$(uname -r) .config

# 清理源码树（如果之前有编译残留）
make mrproper

# 恢复配置
cp /boot/config-$(uname -r) .config

# 自动设置新选项的默认值
make olddefconfig
```

### 4. 启用虚拟化支持
```bash
# 启用虚拟化基础框架
scripts/config --enable CONFIG_VIRTUALIZATION

# 启用 KVM 虚拟机管理程序
scripts/config --enable CONFIG_KVM

# 启用 virtio 驱动
scripts/config --enable CONFIG_VIRT_DRIVERS

# 重新应用配置
make olddefconfig
```

### 5. 解决证书缺失问题（可选）
如果遇到 `openeuler-cert.pem` 缺失错误：
```bash
scripts/config --disable CONFIG_SYSTEM_TRUSTED_KEYS
scripts/config --disable CONFIG_SYSTEM_EXTRA_CERTIFICATE
make olddefconfig
```

### 6. 编译内核镜像
```bash
# 编译 ARM64 内核镜像
make -j$(nproc) Image

# 验证生成的镜像
ls -lh arch/arm64/boot/Image
```

### 7. 编译内核模块
```bash
make -j$(nproc) modules
```

### 8. 验证虚拟化配置
```bash
grep -E "CONFIG_VIRTUALIZATION|CONFIG_KVM" .config
# 应显示:
# CONFIG_VIRTUALIZATION=y
# CONFIG_KVM=y
# CONFIG_KVM_MMIO=y
# CONFIG_KVM_VFIO=y
# CONFIG_KVM_GENERIC_DIRTYLOG_READ_PROTECT=y
# CONFIG_VIRT_DRIVERS=y
```

### 9. 安装（需在目标机器上以 root 权限执行）
```bash
# 安装模块
make modules_install

# 安装内核
make install
```

### 10. 更新引导程序并重启
```bash
# 更新 grub
grub2-mkconfig -o /boot/grub2/grub.cfg

# 重启系统
reboot
```

### 11. 重启后验证
```bash
# 检查 KVM 模块是否加载
lsmod | grep kvm

# 检查虚拟化功能
cat /proc/cpuinfo | grep -i virt
dmesg | grep -i kvm
```

### 关键配置项说明

| 配置项 | 说明 |
|--------|------|
| `CONFIG_VIRTUALIZATION=y` | 启用虚拟化基础框架 |
| `CONFIG_KVM=y` | 启用 KVM 虚拟机管理程序 |
| `CONFIG_KVM_ARM_HOST=y` | 启用 ARM64 Host 支持（如果可用） |
| `CONFIG_VIRT_DRIVERS=y` | 启用 virtio 驱动 |
| `CONFIG_KVM_MMIO=y` | KVM MMIO 设备支持 |
| `CONFIG_KVM_VFIO=y` | KVM VFIO 设备支持 |

### 常见问题

**Q: 编译时提示 `implicit declaration of function 'kvm_compute_layout'`**
A: 检查 `arch/arm64/kvm/Kconfig` 和 `arch/arm64/include/asm/kvm_mmu.h` 是否被意外清空或修改，使用 `git checkout` 恢复。

**Q: 编译时提示 `No rule to make target 'certs/openeuler-cert.pem'`**
A: 如步骤 5 所述，禁用系统信任密钥配置。

**Q: 如何确认编译出的内核支持虚拟化？**
A: 重启后运行 `lsmod | grep kvm`，应该看到 `kvm` 和 `kvm_arm` 模块。

---

## 当前环境配置和需求（2026-04-03）

### 用户需求
用户在OpenEuler ARM64虚机中工作，需要：
1. 编译内核源码（包含stage2页表dump的5个patch）
2. 编译的内核必须支持KVM虚拟化
3. 要能用lkvm静态二进制测试stage2 dump能力
4. 替换当前运行的内核，重启后测试

### 环境信息
| 项目 | 值 |
|------|-----|
| OS | openEuler 24.03 (LTS) aarch64 |
| 源码位置 | /root/openeuler_code/kernel |
| Stage2 Patch目录 | /mnt/kernel/merge2Stage |
| 当前运行内核 | 6.6.0-28.0.0.34.oe2403.aarch64 |
| 新编译内核版本 | 6.6.0+ 或 6.6.0+stage2 |
| lkvm静态二进制 | /usr/local/bin/lkvm |

### Stage2 Patch信息
已合入的5个stage2 dump patch（从新到旧）：
```
630d20bac47f KVM: arm64: Register ptdump with debugfs on guest creation
5087325842a9 arm64: ptdump: Don't override the level when operating on the stage-2 tables
dc1ca2612e5e arm64: ptdump: Use the ptdump description from a local context
38618ceb7f4f arm64: ptdump: Expose the attribute parsing functionality
503bfb13df8c KVM: arm64: Move pagetable definitions to common header
```

### 已完成操作记录
1. `make mrproper` - 清理源码树
2. `make defconfig` - 应用默认配置
3. `make virt.config` - 应用虚拟化配置
4. `make Image -j8` - 编译内核镜像（已完成）
5. `make modules -j8` - 编译内核模块（已完成）
6. `make modules_install` - 安装模块到 /lib/modules/6.6.0-34072-g630d20bac47f
7. 复制内核文件到 /boot/（vmlinuz-6.6.0+, System.map-6.6.0+）
8. `dracut` 生成 initramfs-6.6.0+.img（已完成）
9. `grub2-mkconfig` 更新启动菜单（已完成）
10. lkvm 已复制到 /usr/local/bin/lkvm

### 内核关键配置项
```
CONFIG_KVM=y                    # KVM内置（非模块）
CONFIG_ARM_GIC_V3=y             # ARM GIC v3支持
CONFIG_VIRTIO_BLK=y              # virtio块设备
CONFIG_VIRTIO_NET=y              # virtio网络设备
CONFIG_DEBUG_INFO=y              # 调试信息
CONFIG_PTDUMP_STAGE2_DEBUGFS=y   # Stage2 dump功能（仅stage2模式）
```

### 新内核文件位置
```
/boot/vmlinuz-6.6.0+            # 内核镜像 (23MB)
/boot/initramfs-6.6.0+.img      # initramfs (20MB)
/boot/System.map-6.6.0+         # System map (3.4MB)
/lib/modules/6.6.0-34072-g630d20bac47f/  # 内核模块
```

### GRUB启动项
1. `openEuler (6.6.0-28.0.0.34.oe2403.aarch64)` - 旧内核（当前默认）
2. `openEuler (6.6.0+)` - 新编译的内核

### lkvm测试文件
```
/usr/local/bin/lkvm                              # lkvm静态二进制
/root/openeuler_code/lkvm_test/Image             # 测试用guest kernel image
/root/openeuler_code/lkvm_test/initramfs.cpio.gz # 测试用initramfs
```

### 使用build_repo.sh脚本
```bash
# 编译原生欧拉内核
cd /mnt/kernel/merge2Stage
./build_repo.sh --mode native --all

# 编译stage2 dump内核
cd /mnt/kernel/merge2Stage
./build_repo.sh --mode stage2 --all

# 单独执行某个步骤
./build_repo.sh --mode stage2 --configure
./build_repo.sh --mode stage2 --build
./build_repo.sh --mode stage2 --install
```

### 重启后验证步骤
1. `reboot` 重启系统
2. 在GRUB菜单选择 `openEuler (6.6.0+)`
3. 验证内核版本: `uname -r`
4. 验证KVM可用: `ls /dev/kvm`
5. 测试lkvm运行: `lkvm run --kernel /root/openeuler_code/lkvm_test/Image`

### 设置默认启动项（可选）
```bash
# 查看可用启动项
grep "menuentry" /boot/grub2/grub.cfg

# 设置新内核为默认
grub2-set-default "openEuler (6.6.0+)"
```
