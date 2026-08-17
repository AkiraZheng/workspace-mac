# VFIO ACC 加速器热迁移 PCIe 0x4a (DEVSTA) 校验失败分析

代码库: `/root/code/openeuler_qemu/qemu`

## 1. 现象

```
qemu-system-aarch64: get_pci_config_device: Bad config data: i=0x4a read: 0 device: 8 cmask: ff wmask: 0 w1cmask:0
```

## 2. 寄存器背景

### 2.1 定义

`0x4a` = PCIe Capability 基址 (通常 `0x40`) + `PCI_EXP_DEVSTA` (`0x0a`)

| 位 | 宏 (`include/standard-headers/linux/pci_regs.h`) | 含义 |
|----|------|------|
| 0 | `PCI_EXP_DEVSTA_CED` | Correctable Error Detected |
| 1 | `PCI_EXP_DEVSTA_NFED` | Non-Fatal Error Detected |
| 2 | `PCI_EXP_DEVSTA_FED` | Fatal Error Detected |
| 3 | `PCI_EXP_DEVSTA_URD` | Unsupported Request Detected |

bit 0-3 是 **RW1CS** (Read/Write-1-to-Clear Status) — 硬件自主置位，软件写 1 清零。

错误值 `8` = bit 3 = **URD**。URD 在 AER 中属于**不可纠正 + 非致命** (`pcie_aer_uncor_default_severity`)。

## 3. 迁移中配置空间的值来源

### 3.1 Save 侧 (`hw/pci/pci.c:667-676`)

```c
static int put_pci_config_device(QEMUFile *f, void *pv, size_t size, ...)
{
    const uint8_t **v = pv;
    qemu_put_buffer(f, *v, size);    // 把源端 pdev->config[] 整块序列化进迁移流
}
```

源端配置空间整体 (4096 bytes) 打包进迁移流，**0x4a 的值来自源端**。

### 3.2 Load 侧 (`hw/pci/pci.c:630-664`)

三段式操作：读 → 校验 → 覆盖。

```c
static int get_pci_config_device(QEMUFile *f, void *pv, size_t size,
                                 const VMStateField *field)
{
    PCIDevice *s = container_of(pv, PCIDevice, config);  // 取结构体缓存
    uint8_t *config;

    config = g_malloc(size);

    // ① 从迁移流读取源端保存的全部配置空间
    qemu_get_buffer(f, config, size);

    // ② 逐字节校验: 源端值 vs 目的端缓存值
    for (i = 0; i < size; ++i) {
        if ((config[i] ^ s->config[i]) &
            s->cmask[i] & ~s->wmask[i] & ~s->w1cmask[i]) {
            // 校验失败 → 直接返回，不写回
            error_report("... i=0x%x read: %x device: %x ...",
                         i, config[i], s->config[i], ...);
            return -EINVAL;
        }
    }

    // ③ 校验全部通过 → 用源端值整块覆盖目的端 pdev->config[]
    memcpy(s->config, config, size);
    ...
}
```

**两端的值来源不同:**

| 变量 | 来自 | 含义 |
|------|------|------|
| `config[i]` (打印 `read`) | **源端** QEMU `pdev->config[]`，经迁移流传来 | 源端硬件 pread 的值 |
| `s->config[i]` (打印 `device`) | **目的端** 物理 VF 硬件，`vfio_realize()` 中 `pread()` 一次性读入 | 目的端硬件 DEVSTA 快照 |

**当前 bug**: 流程在 ② 因 0x4a 不匹配而 `return -EINVAL`，`memcpy` 没执行到。如果修了 cmask 让校验通过，**源端 DEVSTA=0 会通过 ③ 的 `memcpy` 写进目的端 `s->config[0x4a]`，覆盖掉旧的 8**。即整个配置空间是从源端整体拷贝到目的端的。

### 3.3 打印字段对应

| 打印 | 代码变量 | 实际含义 |
|------|----------|----------|
| `read` | `config[i]` | 迁移流中读取的值 (**源端** QEMU 保存的) |
| `device` | `s->config[i]` | 目的端 PCIDevice 结构体 `config[]` 缓存值 |
| `cmask` | `s->cmask[i]` | 需校验的位掩码 |
| `wmask` | `s->wmask[i]` | 可写位 (被排除校验) |
| `w1cmask` | `s->w1cmask[i]` | W1C 位 (被排除校验) |

**关键**: `s->config[i]` 不是实时硬件值，是 PCIDevice 结构体内的缓存数组。

### 3.4 本例代入

```
config[0x4a]      = 0x00    ← 源端 DEVSTA 干净
s->config[0x4a]   = 0x08    ← 目的端 缓存 中的 DEVSTA (URD=1)
s->cmask[0x4a]    = 0xFF    ← 要求全部匹配
s->wmask[0x4a]    = 0x00    ← 只读寄存器
s->w1cmask[0x4a]  = 0x00    ← W1C 位未标记

(0x00 ^ 0x08) & 0xFF & ~0x00 & ~0x00
= 0x08 → 非零 → 报错
```

### 3.5 配置空间迁移数据流图

```mermaid
graph TD
    subgraph "迁出端 (源端)"
        A[VF1 硬件配置空间<br/>0x4a = 0x00] -->|pread读取| B[VF1 s->config<br/>0x4a = 0x00]
        B -->|put_pci_config_device<br/>qemu_put_buffer| C[迁移流<br/>config[0x4a] = 0x00]
    end

    subgraph "迁入端 (目的端)"
        D[VF2 硬件配置空间<br/>0x4a = 0x08 URD=1] -->|① vfio_realize时<br/>pread读取| E[VF2 s->config<br/>0x4a = 0x08]
        E -->|② 阶段二迁移开始| F[get_pci_config_device]
        C -->|qemu_get_buffer<br/>从迁移流读取| F
        
        F -->|③ 逐字节校验| G{校验逻辑<br/>(config[i] ^ s->config[i]) &<br/>cmask & ~wmask & ~w1cmask}
        
        G -->|0x4a偏移处| H[config[0x4a] = 0x00<br/>s->config[0x4a] = 0x08<br/>cmask[0x4a] = 0xFF<br/>wmask[0x4a] = 0x00<br/>w1cmask[0x4a] = 0x00]
        
        H --> I[校验计算:<br/>(0x00 ^ 0x08) & 0xFF & ~0x00 & ~0x00<br/>= 0x08 ≠ 0]
        I -->|校验失败| J[返回 -EINVAL<br/>打印错误信息<br/>虚机挂死]
        
        I -->|如果校验通过<br/>(修复后)| K[memcpy覆盖<br/>s->config = config<br/>0x4a变为0x00]
    end

    subgraph "关键差异说明"
        L[寄存器0x4a含义:<br/>PCI_EXP_DEVSTA<br/>bit3=URD位]
        M[cmask=0xFF原因:<br/>vfio_setup_pcie_cap<br/>pci_add_capability<br/>将PCIe Cap全部设为校验]
        N[w1cmask=0x00原因:<br/>pcie_cap_deverr_init<br/>仅QEMU模拟设备调用<br/>VFIO透传未设置]
        O[根本原因:<br/>目的端硬件FLR后<br/>pdev->config缓存未刷新<br/>仍为初始pread旧值]
    end

    style H fill:#ff9999
    style I fill:#ff9999
    style J fill:#ff3333,color:#fff
    style L fill:#ffff99
    style M fill:#ffff99
    style N fill:#ffff99
    style O fill:#ffff99
```

## 4. 根因

### 4.1 cmask[0x4a] = 0xFF 的来源

VFIO 设备在 `vfio_setup_pcie_cap()` (`hw/vfio/pci.c:2000`) 中调用 `pci_add_capability()`:

```c
// hw/vfio/pci.c:2119
pos = pci_add_capability(&vdev->pdev, PCI_CAP_ID_EXP, pos, size, errp);

// hw/pci/pci.c:2511
memset(pdev->cmask + offset, 0xFF, size);   // PCIe Cap 区域全部要求匹配
```

### 4.2 w1cmask[0x4a] = 0x00 的原因

`pcie_cap_deverr_init()` (`hw/pci/pcie.c:301-311`) 正确设置了 DEVSTA 的 w1cmask:

```c
void pcie_cap_deverr_init(PCIDevice *dev)
{
    uint32_t pos = dev->exp.exp_cap;
    pci_long_test_and_set_mask(dev->w1cmask + pos + PCI_EXP_DEVSTA,
                               PCI_EXP_DEVSTA_CED | PCI_EXP_DEVSTA_NFED |
                               PCI_EXP_DEVSTA_FED | PCI_EXP_DEVSTA_URD);
}
```

但该函数仅被 **QEMU 模拟设备** 调用 (NVMe, virtio, pci-bridge, CXL)，**VFIO 透传设备不调用**。

VFIO 路径 (`vfio_setup_pcie_cap` → `pci_add_capability`) 没有设置 DEVSTA 的 w1cmask，`w1cmask[0x4a]` 保持 `g_malloc0` 初始值 `0x00`。

### 4.3 与 LNKSTA 的对比

`pcie_cap_v1_fill()` (`hw/pci/pcie.c:83-87`) 对同是状态寄存器的 LNKSTA 做了正确处理:

```c
/* We changed link status bits over time, and changing them across
 * migrations is generally fine as hardware changes them too.
 * Let's not bother checking. */
pci_set_word(cmask + PCI_EXP_LNKSTA, 0);   // 不校验链路状态
```

DEVSTA 没有对应处理。

## 5. 目的端迁移流程 (代码库实际路径)

代码库位于 `/root/code/openeuler_qemu/qemu`，以下均为该路径下的相对路径。

### 5.1 完整时序

```
目的端 QEMU -incoming 启动
      │
      ▼
① pci_qdev_realize()                         ← 标准 PCI 设备初始化
   ├─ pci_init_cmask()                         ← pci.c:849   (只设 header 的 cmask)
   ├─ pci_init_wmask()                         ← pci.c:861   设 wmask (header 后可写)
   └─ pci_init_w1cmask()                       ← pci.c:876   设 header W1C 位
      │
      ▼
② vfio_realize()                              ← hw/vfio/pci.c:2993
   │
   ├─ vfio_attach_device()                     ← :3046      绑定 IOMMU
   │
   ├─ vfio_populate_device()                   ← :3053      读取 BAR / FLR / AER 信息
   │
   ├─ pread(fd, pdev->config, size, offset)    ← :3060      ★ 从硬件读全部配置空间
   │   ★ pdev->config[0x4a] = 硬件当时的 DEVSTA 值
   │   ★ 此后 pdev->config[] 永不整体 re-read
   │
   ├─ vfio_add_capabilities()                  ← set up 时调用
   │   └─ vfio_add_std_cap() → vfio_setup_pcie_cap()  ← :2000
   │       └─ pci_add_capability(PCI_CAP_ID_EXP)        ← :2119
   │           ├─ cmask[0x40..] = 0xFF                   ← 全部要求校验
   │           └─ w1cmask 不设 (保持 0)                   ← W1C 位未标记
   │
   ├─ vfio_migration_realize()                 ← :3262
   │   └─ register_savevm_live()               ← 注册 SaveVMHandlers
   │       │   .save_setup    = vfio_save_setup
   │       │   .save_state    = vfio_save_state       ← 保存配置空间
   │       │   .load_setup    = vfio_load_setup       ← 设 RESUMING
   │       │   .load_state    = vfio_load_state       ← 加载状态
   │
   └─ (realize 中无显式 reset 调用)
      │
      ▼
③ qemu_system_reset()                         ← VM 初始化系统 reset
   └─ vfio_pci_reset()                         ← hw/vfio/pci.c:3335 (DeviceClass->reset)
       ├─ vfio_pci_pre_reset()                 ← :2431  禁用中断、停 DMA
       ├─ ioctl(VFIO_DEVICE_RESET)             ← :3353  FLR
       │   ★ 硬件 DEVSTA 清零
       │   ★ pdev->config[0x4a] 不更新!
       └─ vfio_pci_post_reset()                ← :2468  INTx 重使能 + BAR 清零
      │
      ▼
    VM 启动运行... 迁移开始...
      │
      ▼
④ vfio_load_setup()                           ← migration.c:572
   └─ vfio_migration_set_state(RESUMING)       ← ioctl 切换内核 VFIO 状态
      │
      ▼
⑤ vfio_load_state()                           ← migration.c:590
   │
   ├─ [迭代] DEV_DATA_STATE 块                 ← 写设备状态数据到 VFIO fd
   │
   └─ DEV_CONFIG_STATE                        ← :602
       └─ vfio_load_device_config_state()     ← :195
           └─ vfio_pci_load_config()           ← :2645
               └─ vmstate_load_state(&vmstate_vfio_pci_config)
                   └─ get_pci_config_device()  ← pci.c:630
                       │  config[0x4a] = 0x00  (迁移流, 源端)
                       │  s->config[0x4a] = 0x08 (缓存, ② 时刻读的旧值)
                       │
                       └─ 校验失败! 0x08 & 0xFF & 0xFF & 0xFF = 0x08
```

### 5.2 关键数据结构

`s->config[]` (即 `pdev->config[]`) 的更新点:

| 时机 | 事件 | 代码位置 |
|------|------|----------|
| ② | `pread()` 从硬件一次性读入 | `hw/vfio/pci.c:3060` |
| guest 写配置 | `pci_default_write_config()` 按 wmask 过滤写入 | `hw/vfio/pci.c` 多处 |
| ⑤ 校验通过后 | `memcpy(s->config, config, size)` 覆盖为源端值 | `hw/pci/pci.c:652` |

DEVSTA (`0x4a`) 的 `wmask = 0`，不会被 `pci_default_write_config` 更新。唯一的更新路径是初始 `pread()` 和迁移成功后的 `memcpy`。

### 5.3 `pdev->config[0x4a]` 为何是旧值

```
② pread(硬件) → pdev->config[0x4a] = 8    ← 写缓存
③ FLR       → 硬件 DEVSTA = 0              ← 硬件变了
⑤ config 校验: s->config[0x4a] = 8          ← 缓存未更新
```

`vfio_pci_post_reset()` (`:2468`) 只做了 INTx 重使能和 BAR 清零，**没有 `pread()` 刷新缓存**。

### 5.4 `pread()` 首次读到 0x08 是否表示硬件有问题

**不是。** 初始读到 URD=1 不代表硬件缺陷，完全是正常行为。

#### DEVSTA 的读写机制

DEVSTA 是只读状态寄存器，PCIe 规范规定：

| 操作 | 行为者 | 机制 |
|------|--------|------|
| **置 1** | **硬件** | PCIe 控制器收到 VF 不支持的 TLP 时自主置位 URD |
| **清 0** | **软件** | 往该位写 1 (W1C) 或通过 FLR 清零 |

软件**无法**将 URD 置 1。`pdev->config[]` 的写入路径对此也无能为力：

- `pci_set_byte(pdev->config + 0x4a, ...)` — 全量搜索 `hw/vfio/pci.c` 无任何代码对此偏移直接写入
- `pci_default_write_config()` — wmask[0x4a] = 0，写入被过滤
- guest 通过 VFIO 写配置 — 同样被 wmask 过滤

唯一的写入是 `pread()` (`:3060`) 从硬件读入的值，之后直到 `get_pci_config_device()` 从未被更新。**`pdev->config[0x4a]` 就是 `pread()` 那一刻硬件 DEVSTA 的快照，之后无任何代码路径修改它。**

#### 为什么 VF 的 URD 初始可能为 1

VF 的 PCIe capability 通常是截断的（部分寄存器不实现）。以下情况都会触发硬件置位 URD：

- **BIOS/固件枚举阶段**: PF 扫描 VF 配置空间时访问了 VF 不支持的寄存器偏移
- **PF 驱动加载**: PF 对 VF 做初始化时触碰了不支持的偏移
- **前次使用未清理**: 上一轮 QEMU 或 host 驱动退出前未清 DEVSTA
- **FLR 行为差异**: 部分硬件在 FLR 过程中自身可能产生短暂的 unsupported request

**源端为什么是 0:** 源端设备上有 guest 驱动正常运行，DEVSTA 的 W1C 位早已被驱动通过 AER 处理或 FLR 清理过。目的端是全新 open，还没人清理。两端值天然不同是正常现象，不表示任何一端硬件有故障。

### 5.5 新发现: VF 创建时 URD 已为 1

通过 host 侧 `sriov_numvfs` 创建 VF 时，直接 `devmem` 读 ECAM 空间发现 **URD 在 VF 刚刚创建时就已经是 1**，无需 guest 或 QEMU 介入。

#### 写入 sriov_numvfs 后的完整时序

```
echo N > sriov_numvfs
  └─ sriov_numvfs_store()                         [iov.c:424]
       └─ driver->sriov_configure(pdev, N)          // e.g. hisi_qm_sriov_configure
            └─ pci_enable_sriov()                   [iov.c:1074]
                 └─ sriov_enable()                  [iov.c:606]
                      ├─ pci_enable_resources()      // 使能 IOV BAR
                      ├─ pcibios_sriov_enable()      // 架构级回调
                      ├─ pci_iov_set_numvfs()        // 写 NUM_VF 寄存器
                      ├─ ★ 写 PCI_SRIOV_CTRL: VFE|MSE
                      │    pci_cfg_access_lock()
                      │    pci_write_config_word()   // VFE + MSE 位置位
                      │    msleep(100)               // 等待硬件稳定
                      │    pci_cfg_access_unlock()
                      └─ sriov_add_vfs() → pci_iov_add_virtfn()
                           ├─ pci_setup_device()     // 探测 VF 的 cfg_size
                           ├─ pci_device_add()       // 初始化 capability (AER/ATS...)
                           └─ pci_bus_add_device()   // 触发 VF 驱动绑定
```

#### URD=1 的触发窗口

VF 的 PCIe config space 在 `pci_write_config_word(dev, iov->pos + PCI_SRIOV_CTRL, VFE|MSE)` 之后、`msleep(100)` 期间即已在硬件层面使能。URD 可能在此窗口内被置位:

| 时机 | 事件 | URD 状态 |
|------|------|----------|
| VF 硬件上电 | VFE 置位 → VF 逻辑开始初始化 | 硬件初始化过程中可能产生内部 unsupported request |
| `msleep(100)` | 等待硬件稳定 | 若硬件在此阶段有内部探测行为，URD 被置 1 |
| `pci_setup_device()` | 内核枚举 VF 配置空间 | 内核访问了 VF 未实现的 capability 偏移 → URD 置 1 |
| `pci_device_add()` | AER/ATS 等子系统初始化 | 进一步读取可能触发更多 URD |

#### 与 SEC/HRPE 对比

SEC 和 HRPE 没有此问题，推测原因:

- **不同 PCIe  topology**: SEC/HRPE 的 VF 内部逻辑在 VFE 使能后不会产生 URD
- **内部实现差异**: 本节点的 SRIOV VF 实现可能在某些只读寄存器上返回 Unsupported Request，而 SEC/HRPE 的实现更完整
- **驱动初始化顺序**: 可能是 PF 驱动在 `sriov_configure` 中做的准备操作不同

#### 影响分析

这意味着 URD=1 的问题在 **host 内核侧 VF 创建时就已经固化**（写入硬件寄存器），不是 guest 行为导致，也不是 QEMU 引入：

```
sriov_numvfs 创建 VF
    │  URD 在 msleep(100) 或 pci_setup_device 阶段被硬件置 1
    ▼
host 侧 VF 的 DEVSTA.URD = 1     ← ★ 源头在这里
    │
    ▼
QEMU vfio_realize() pread() → s->config[0x4a] = 0x08  ★ 只是把硬件值读入缓存
    │
    ▼
目的端 pread 的旧值 0x08 与源端迁移流 0x00 不匹配 → 校验失败
```

即使 `vfio_pci_post_reset()` 刷新了缓存（假设修复），也只是从软件缓存层面掩盖问题——**硬件 DEVSTA 的 URD 位在 VF 创建之初就已经是 1**。真正彻底解决需要硬件团队确认 VF 创建过程中触发 URD 的根因。

## 6. 涉及的关键文件

| 文件 | 行号 | 内容 |
|------|------|------|
| `hw/vfio/pci.c` | 2993-3271 | `vfio_realize()` 设备实例化 |
| `hw/vfio/pci.c` | 3060-3062 | `pread()` 从硬件读配置空间 |
| `hw/vfio/pci.c` | 2000-2128 | `vfio_setup_pcie_cap()` PCIe cap 初始化 |
| `hw/vfio/pci.c` | 2119-2120 | `pci_add_capability(PCI_CAP_ID_EXP)` |
| `hw/vfio/pci.c` | 3335-3372 | `vfio_pci_reset()` FLR / RESET |
| `hw/vfio/pci.c` | 2431-2466 | `vfio_pci_pre_reset()` 前置操作 |
| `hw/vfio/pci.c` | 2468-2487 | `vfio_pci_post_reset()` 后置操作 (不刷新 pdev->config) |
| `hw/vfio/pci.c` | 2638-2643 | `vfio_pci_save_config()` 迁移保存 |
| `hw/vfio/pci.c` | 2645-2683 | `vfio_pci_load_config()` 迁移加载 |
| `hw/vfio/migration.c` | 178-193 | `vfio_save_device_config_state()` |
| `hw/vfio/migration.c` | 195-220 | `vfio_load_device_config_state()` |
| `hw/vfio/migration.c` | 572-578 | `vfio_load_setup()` RESUMING 状态 |
| `hw/vfio/migration.c` | 590-639 | `vfio_load_state()` 目的端状态机 |
| `hw/vfio/migration.c` | 669-683 | `SaveVMHandlers` 迁移回调表 |
| `hw/pci/pci.c` | 630-664 | `get_pci_config_device()` 配置校验入口 |
| `hw/pci/pci.c` | 2472-2512 | `pci_add_capability()` 设置 cmask=0xFF |
| `hw/pci/pci.c` | 849-859 | `pci_init_cmask()` 初始化 header cmask |
| `hw/pci/pci.c` | 876-886 | `pci_init_w1cmask()` 初始化 header w1cmask |
| `hw/pci/pcie.c` | 53-88 | `pcie_cap_v1_fill()` LNKSTA cmask=0 + DEVSTA 漏网 |
| `hw/pci/pcie.c` | 301-312 | `pcie_cap_deverr_init()` 设置 DEVSTA w1cmask (VFIO 不调用) |
| `include/standard-headers/linux/pci_regs.h` | - | `PCI_EXP_DEVSTA_*` 位定义 |

## 7. 修复方向

与 LNKSTA 处理对称，对 DEVSTA 跳过校验。

**方案 A** (推荐): 在 `vfio_setup_pcie_cap()` 中，`pci_add_capability()` 之后:

```c
/* Status registers change across migrations, don't check */
pci_set_word(vdev->pdev.cmask + pos + PCI_EXP_DEVSTA, 0);
```

**方案 B**: 设置 w1cmask，与 `pcie_cap_deverr_init()` 一致:

```c
pci_word_test_and_set_mask(vdev->pdev.w1cmask + pos + PCI_EXP_DEVSTA,
                           PCI_EXP_DEVSTA_CED | PCI_EXP_DEVSTA_NFED |
                           PCI_EXP_DEVSTA_FED | PCI_EXP_DEVSTA_URD);
```

方案 A 更彻底 (整个寄存器不校验)，方案 B 更精细 (仅排除 W1C 位)。推荐 A，与 LNKSTA 一致。
