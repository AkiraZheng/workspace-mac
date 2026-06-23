# VFIO 加速器热迁移中 PCIe 配置空间 0x4a (DEVSTA) 校验失败分析

## 1. 现象

ACC 加速器 VF 热迁移时，目的端 QEMU 报错：

```
qemu-system-aarch64: get_pci_config_device: Bad config data: i=0x4a read: 0 device: 8 cmask: ff wmask: 0 w1cmask:0
```

## 2. 背景知识

### 2.1 寄存器定义

`0x4a` = `PCIe Capability 基址 (通常 0x40)` + `PCI_EXP_DEVSTA (0x0a)`

| 位 | 宏 | 含义 | 类型 |
|----|-----|------|------|
| 0 | `PCI_EXP_DEVSTA_CED` | Correctable Error Detected | RW1CS |
| 1 | `PCI_EXP_DEVSTA_NFED` | Non-Fatal Error Detected | RW1CS |
| 2 | `PCI_EXP_DEVSTA_FED` | Fatal Error Detected | RW1CS |
| 3 | `PCI_EXP_DEVSTA_URD` | Unsupported Request Detected | RW1CS |
| 4 | `PCI_EXP_DEVSTA_AUXPD` | AUX Power Detected | RO |
| 5 | `PCI_EXP_DEVSTA_TRPND` | Transactions Pending | RO |

其中 bit 0-3 在硬件上是 **RW1CS**（Read/Write-1-to-Clear Status）位，反映设备运行时检测到的错误状态。

错误值 `8` = bit 3 = **URD (Unsupported Request Detected)**。

编译器声明见 `include/standard-headers/linux/pci_regs.h:532-536`：

```c
#define PCI_EXP_DEVSTA        0x0a
#define PCI_EXP_DEVSTA_CED    0x0001
#define PCI_EXP_DEVSTA_NFED   0x0002
#define PCI_EXP_DEVSTA_FED    0x0004
#define PCI_EXP_DEVSTA_URD    0x0008
```

### 2.2 URD 错误等级

在 PCIe AER 中，URD（`PCI_ERR_UNC_UNSUP`）属于**不可纠正 + 非致命**错误：

```c
// hw/pci/pcie_aer.c:47-70
static uint32_t pcie_aer_uncor_default_severity(uint32_t status)
{
    switch (status) {
    case PCI_ERR_UNC_UNSUP:              // ← URD 在这里
        return PCI_ERR_ROOT_CMD_NONFATAL_EN;  // 非致命
    case PCI_ERR_UNC_DLP:                // 真正致命的
    case PCI_ERR_UNC_MALF_TLP:
        return PCI_ERR_ROOT_CMD_FATAL_EN;
    ...
    }
}
```

URD 可通过 `DEVCTL.URRE` 位控制是否上报（`pcie_aer.c:568`）：

```c
if (inj->unsupported_request && !(inj->devctl & PCI_EXP_DEVCTL_URRE)) {
    return false;  // 不上报
}
```

## 3. 校验逻辑解析

### 3.1 核心校验代码

`get_pci_config_device()` 是迁移 **load（目的端）**回调，位于 `hw/pci/pci.c:803-837`：

```c
static int get_pci_config_device(QEMUFile *f, void *pv, size_t size,
                                 const VMStateField *field)
{
    PCIDevice *s = container_of(pv, PCIDevice, config);
    uint8_t *config;

    config = g_malloc(size);
    qemu_get_buffer(f, config, size);        // 从迁移流读取源端保存的配置

    for (i = 0; i < size; ++i) {
        // 校验：两端的差异位 & (必须检查的位 & 非可写位 & 非W1C位)
        if ((config[i] ^ s->config[i]) &
            s->cmask[i] & ~s->wmask[i] & ~s->w1cmask[i]) {
            // config[i] = 迁移流的值 (源端)
            // s->config[i] = 目的端 PCIDevice 当前值 (来自硬件)
            error_report("%s: Bad config data: i=0x%x read: %x device: %x "
                         "cmask: %x wmask: %x w1cmask:%x", ...,
                         i, config[i], s->config[i],
                         s->cmask[i], s->wmask[i], s->w1cmask[i]);
            return -EINVAL;
        }
    }
    memcpy(s->config, config, size);         // 校验通过则覆盖
    ...
}
```

### 3.2 错误打印中各字段含义

| 打印字段 | 代码变量 | 真正含义 |
|----------|----------|----------|
| `read` | `config[i]` | **迁移流中读取的值（源端 QEMU 保存的）** |
| `device` | `s->config[i]` | **目的端 PCIDevice 当前值（vfio_pci_config_setup 从硬件 pread 出来的）** |
| `cmask` | `s->cmask[i]` | 需要校验的位掩码 |
| `wmask` | `s->wmask[i]` | 可写位（被排除校验） |
| `w1cmask` | `s->w1cmask[i]` | W1C 位（被排除校验） |

**注意命名容易误解**：`read` 不是"从硬件 read"，而是"从迁移流 read"；`device` 才是目的端硬件的真实值。

### 3.3 本例的值代入

```
config[0x4a] = 0x00       ← 源端 DEVSTA 干净无错误
s->config[0x4a] = 0x08    ← 目的端物理 VF 的 DEVSTA 已置 URD=1

校验计算：
(0x00 ^ 0x08) & 0xFF & ~0x00 & ~0x00
= 0x08 & 0xFF & 0xFF & 0xFF
= 0x08                     → 非零，校验失败
```

## 4. 根因分析

### 4.1 cmask[0x4a] = 0xFF 的来源

VFIO 设备在 `vfio_setup_pcie_cap()` (`hw/vfio/pci.c:2292`) 中通过 `pci_add_capability()` 注册 PCIe Capability：

```c
// hw/pci/pci.c:2694
/* Check capability by default */
memset(pdev->cmask + offset, 0xFF, size);
```

这将 PCIe Capability 区域（含 DEVSTA 所在的 0x4a）的 `cmask` 全部设为 `0xFF`，要求迁移时每个字节都匹配。

### 4.2 w1cmask[0x4a] = 0 的原因

全 QEMU 只有一处设置了 DEVSTA 的 w1cmask —— `pcie_cap_deverr_init()` (`hw/pci/pcie.c:372-374`)：

```c
void pcie_cap_deverr_init(PCIDevice *dev)
{
    uint32_t pos = dev->exp.exp_cap;
    pci_long_test_and_set_mask(dev->w1cmask + pos + PCI_EXP_DEVSTA,
                               PCI_EXP_DEVSTA_CED | PCI_EXP_DEVSTA_NFED |
                               PCI_EXP_DEVSTA_FED | PCI_EXP_DEVSTA_URD);
}
```

但该函数**仅被 QEMU 模拟设备调用**（NVMe、virtio、CXL、pci-bridge），**VFIO 透传设备路径从不调用**它：

```c
// hw/vfio/pci.c:2172 - vfio_setup_pcie_cap()
pos = pci_add_capability(pdev, PCI_CAP_ID_EXP, pos, size, errp);
pdev->exp.exp_cap = pos;
// ← 没有调用 pcie_cap_deverr_init()，也没有单独设置 w1cmask
```

`hw/vfio/` 整个目录下：
- 无任何 `w1cmask` 引用
- 无任何 `DEVSTA` 引用

因此 VFIO 设备的 `w1cmask[0x4a]` 保持 `g_malloc0` 的初始值 `0x00`。

### 4.3 如果 w1cmask 正确设置的对比

假如 `w1cmask[0x4a] = 0x0F`（含 URD bit），则校验计算变为：

```
(0x00 ^ 0x08) & 0xFF & ~0x00 & ~0x0F
= 0x08 & 0xFF & 0xFF & 0xF0
= 0x08 & 0xF0
= 0x00   → 校验通过 ✓
```

W1C 位被排除校验 —— 这本身就是 `~w1cmask` 项的设计意图。

### 4.4 与 LNKSTA 的对比

`pcie_cap_v1_fill()` (`hw/pci/pcie.c:107-111`) 对同是状态寄存器的 LNKSTA 做了正确处理：

```c
/* We changed link status bits over time, and changing them across
 * migrations is generally fine as hardware changes them too.
 * Let's not bother checking. */
pci_set_word(cmask + PCI_EXP_LNKSTA, 0);
```

DEVSTA 缺少对应的处理，它是漏网之鱼。

## 5. 迁移流程与复位时序

### 5.1 目的端完整时序

```
目的端 QEMU 启动
      │
      ▼
① vfio_pci_realize()                         ← 设备实例化
   ├─ vfio_pci_config_setup()                 ← pread() 读硬件配置空间 → pdev->config[]
   │   ★ 此时 pdev->config[0x4a] 已是目的端硬件的真实 DEVSTA 值（可能=0x08）
   ├─ vfio_add_capabilities()                 ← setup PCIe/MSI/VSC 等 cap
   │   │  pci_add_capability() 设置 cmask=0xFF
   │   │  不调用 pcie_cap_deverr_init()
   │   └─ w1cmask[0x4a] 保持 0x00
   └─ vfio_pci_reset()                        ← ioctl(VFIO_DEVICE_RESET) 触发 FLR
           ↓  (PCIe spec 规定 FLR 应清零 DEVSTA，但 FLR 本身或后续访问可能重新触发 URD)
      VM 启动运行后开始接收迁移
      │
      ▼
② vfio_load_setup()                          ← migration.c:708
   └─ ioctl 切换 device_state → RESUMING
      (纯状态切换，不做 reset)
      │
      ▼
③ vfio_load_state()                          ← migration.c:739 读迁移流
   ├─ DEV_DATA_STATE 块                        ← 写设备数据到 VFIO fd
   │
   └─ DEV_CONFIG_STATE                        ← migration.c:760
       └─ vfio_load_device_config_state()
           └─ vfio_pci_load_config()
               └─ get_pci_config_device()       ★ 在这里校验 config[i] vs s->config[i]
                   → s->config[0x4a]==0x08 ≠ config[0x4a]==0x00
                   → 校验失败！
```

### 5.2 复位机制

`vfio_pci_reset()` (`hw/vfio/pci.c:3641`) 的复位尝试顺序：

```
1. vdev->resetfn          ← 设备特定复位回调（如有）
2. VFIO_DEVICE_RESET      ← ioctl FLR（对支持 FLR 的 ACC VF 生效）
3. hot_reset               ← PCIe hot reset (bus reset)
4. VFIO_DEVICE_RESET      ← PM reset（如设备无 FLR 但有 PM reset）
```

ACC VF 通过 `vfio_check_pcie_flr()` 检测 `PCI_EXP_DEVCAP_FLR` (v2.2+) 或 `vfio_check_af_flr()` 检测 AF FLR (v2.0)，确认支持 FLR 后走第 2 路径。

### 5.3 DEVSTA 在迁移中怎么传递的？

**QEMU VFIO 框架**负责 PCI 配置空间迁移（非内核 ACC 驱动）：

**源端 (save)**：
```
vfio_save_state() → vfio_save_device_config_state()
    → vfio_pci_save_config()
        → vmstate_save_state(&vmstate_vfio_pci_config)
            → put_pci_config_device()
                → qemu_put_buffer(f, pdev->config, 4096)  // 整体序列化
```

**目的端 (load)**：
```
vfio_load_state() → DEV_CONFIG_STATE
    → vfio_load_device_config_state()
        → vfio_pci_load_config()
            → vmstate_load_state(&vmstate_vfio_pci_config)
                → get_pci_config_device()
                    → qemu_get_buffer(f, config, 4096)     // 读迁移流
                    → 逐字节与 s->config[] 校验
                    → memcpy(s->config, config, 4096)      // 校验通过则覆盖
                    → vfio_pci_write_config(PCI_COMMAND)   // 写回 COMMAND 寄存器
```

**内核 ACC 驱动** (`hisi_acc_vfio_pci.c`) 的迁移数据 (`struct acc_vf_data`) 只包含 QM 状态和 DMA 地址，不包含 PCI 配置空间。PCI 配置空间完全由 QEMU VFIO 框架处理。

## 6. 修复方案

### 方案 A：清除 DEVSTA 的 cmask（推荐，与 LNKSTA 对称）

在 `pcie_cap_v1_fill()` 或 `vfio_setup_pcie_cap()` 中：

```c
pci_set_word(cmask + PCI_EXP_DEVSTA, 0);  // 不校验设备状态寄存器
```

与已有的 LNKSTA 处理完全对称：

```c
// pcie.c:111 — 已有
pci_set_word(cmask + PCI_EXP_LNKSTA, 0);
```

### 方案 B：设置 DEVSTA 的 w1cmask

在 `vfio_setup_pcie_cap()` 中 `pci_add_capability()` 之后：

```c
pci_word_test_and_set_mask(pdev->w1cmask + pos + PCI_EXP_DEVSTA,
                           PCI_EXP_DEVSTA_CED | PCI_EXP_DEVSTA_NFED |
                           PCI_EXP_DEVSTA_FED | PCI_EXP_DEVSTA_URD);
```

方案 A 更彻底（DEVSTA 整个寄存器都不校验），方案 B 更精细（仅排除 W1C 位）。推荐方案 A，与 LNKSTA 一致。

## 7. 涉及的关键文件

| 文件 | 关键行 | 内容 |
|------|--------|------|
| `hw/pci/pci.c` | 803-837 | `get_pci_config_device()` 配置空间校验逻辑 |
| `hw/pci/pci.c` | 815-816 | `(config[i] ^ s->config[i]) & cmask[i] & ~wmask[i] & ~w1cmask[i]` |
| `hw/pci/pci.c` | 2690-2694 | `pci_add_capability()` 设置 `cmask = 0xFF` |
| `hw/pci/pcie.c` | 107-111 | LNKSTA cmask 清零（DEVSTA 的参照） |
| `hw/pci/pcie.c` | 364-374 | `pcie_cap_deverr_init()` 设置 DEVSTA w1cmask（VFIO 未调用） |
| `hw/vfio/pci.c` | 2172-2299 | `vfio_setup_pcie_cap()` VFIO PCIe cap 初始化 |
| `hw/vfio/pci.c` | 2292 | `pci_add_capability(PCI_CAP_ID_EXP)` |
| `hw/vfio/pci.c` | 2877-2883 | `vfio_pci_save_config()` 迁移保存配置 |
| `hw/vfio/pci.c` | 2885-2905 | `vfio_pci_load_config()` 迁移加载配置 |
| `hw/vfio/pci.c` | 3286-3302 | `vfio_pci_config_setup()` 从硬件 pread 配置空间 |
| `hw/vfio/pci.c` | 3641-3683 | `vfio_pci_reset()` FLR / VFIO_DEVICE_RESET |
| `hw/vfio/migration.c` | 255-278 | `vfio_save_device_config_state()` |
| `hw/vfio/migration.c` | 280-304 | `vfio_load_device_config_state()` |
| `hw/vfio/migration.c` | 708-725 | `vfio_load_setup()` 设置 RESUMING |
| `hw/vfio/migration.c` | 739-790 | `vfio_load_state()` 目的端状态机 |
| `hw/vfio/migration.c` | 840-860 | `SaveVMHandlers` 迁移回调表 |
| `include/standard-headers/linux/pci_regs.h` | 532-536 | `PCI_EXP_DEVSTA_*` 位定义 |
