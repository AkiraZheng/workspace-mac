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

## 3. 校验逻辑 (`hw/pci/pci.c:630-664`)

```c
static int get_pci_config_device(QEMUFile *f, void *pv, size_t size,
                                 const VMStateField *field)
{
    PCIDevice *s = container_of(pv, PCIDevice, config);  // 取结构体缓存
    uint8_t *config;

    config = g_malloc(size);
    qemu_get_buffer(f, config, size);      // 从迁移流读取 (源端保存的值)

    for (i = 0; i < size; ++i) {
        // 校验公式:
        // (两端差异位) & (cmask 需检查的位) & (~wmask 排除可写位) & (~w1cmask 排除W1C位)
        if ((config[i] ^ s->config[i]) &
            s->cmask[i] & ~s->wmask[i] & ~s->w1cmask[i]) {
            error_report("... i=0x%x read: %x device: %x cmask: %x wmask: %x w1cmask:%x",
                         i, config[i], s->config[i], ...);
            return -EINVAL;
        }
    }
    memcpy(s->config, config, size);       // 校验通过则写回缓存
    ...
}
```

### 3.1 打印字段对应

| 打印 | 代码变量 | 实际含义 |
|------|----------|----------|
| `read` | `config[i]` | 迁移流中读取的值 (**源端** QEMU 保存的) |
| `device` | `s->config[i]` | 目的端 PCIDevice 结构体 `config[]` 缓存值 |
| `cmask` | `s->cmask[i]` | 需校验的位掩码 |
| `wmask` | `s->wmask[i]` | 可写位 (被排除校验) |
| `w1cmask` | `s->w1cmask[i]` | W1C 位 (被排除校验) |

**关键**: `s->config[i]` 不是实时硬件值，是 PCIDevice 结构体内的缓存数组。

### 3.2 本例代入

```
config[0x4a]      = 0x00    ← 源端 DEVSTA 干净
s->config[0x4a]   = 0x08    ← 目的端 缓存 中的 DEVSTA (URD=1)
s->cmask[0x4a]    = 0xFF    ← 要求全部匹配
s->wmask[0x4a]    = 0x00    ← 只读寄存器
s->w1cmask[0x4a]  = 0x00    ← W1C 位未标记

(0x00 ^ 0x08) & 0xFF & ~0x00 & ~0x00
= 0x08 → 非零 → 报错
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

### 5.4 URD 为什么是 1

URD 是硬件自主行为 — 设备收到不支持 TLP 时自动置位。最可能在步骤② `pread()` 之前就已经被置位了 (例如 PF-VF 通信、BIOS 枚举、或前次使用未清零)。源端因为有 guest 驱动运行，DEVSTA 的 W1C 位已被驱动清理。

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
