# HDBSS VFIO Migration Bug - Patch 使用指南

## 一、Patch 文件列表

| 文件名 | 类型 | 用途 |
|--------|------|------|
| `0001-kernel-hdbss-vfio-debug.patch` | Debug | Kernel HDBSS MMIO 处理调试 |
| `0002-kernel-hdbss-mmio-bugfix.patch` | Bug Fix | **修复 DBM 用于 MMIO 的 bug** |
| `0003-qemu-vfio-config-debug.patch` | Debug | QEMU VFIO config space 调试 |
| `0004-qemu-vfio-cmask-bugfix.patch` | Bug Fix | **修复 VFIO migration cmask 验证 bug** |

---

## 二、Kernel Patch 使用

### 2.1 Bug Fix Patch (必须应用)

**文件**: `0002-kernel-hdbss-mmio-bugfix.patch`

**修复内容**: 防止 DBM 用于 VFIO MMIO 区域

```bash
# 应用 patch
cd /root/openeuler/kernel
git apply /mnt/shared/HDBSS/HDBSS_v4_patch/DS/0002-kernel-hdbss-mmio-bugfix.patch

# 验证修改
grep "!device && kvm->enable_hdbss" arch/arm64/kvm/mmu.c

# 编译内核
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc)

# 部署内核到测试环境
```

**修改说明**:
```c
// arch/arm64/kvm/mmu.c:1682
#ifdef CONFIG_ARM64_HDBSS
    if (!device && kvm->enable_hdbss && logging_active)  // ← 添加 !device
        prot |= KVM_PGTABLE_PROT_DBM;
#endif
```

### 2.2 Debug Patch (可选，用于调试)

**文件**: `0001-kernel-hdbss-vfio-debug.patch`

**调试内容**: HDBSS MMIO fault 处理、DBM 决策、buffer 内容

```bash
# 应用 patch (在 bug fix 之后)
git apply /mnt/shared/HDBSS/HDBSS_v4_patch/DS/0001-kernel-hdbss-vfio-debug.patch

# 编译并部署

# 启用 kernel log
echo 8 > /proc/sys/kernel/printk

# 运行测试后收集 log
dmesg | grep HDBSS_DEBUG > /tmp/kernel_hdbss_debug.log
```

**关键调试点**:
- `HDBSS_DEBUG_MMIO_FAULT`: MMIO fault 检测
- `HDBSS_DEBUG_DBM_DECISION`: DBM 添加决策条件
- `HDBSS_DEBUG_DBM_RESULT`: DBM 添加结果
- `HDBSS_DEBUG_FLUSH_ENTRY`: HDBSS buffer 脏页内容

---

## 三、QEMU Patch 使用

### 3.1 Bug Fix Patch (建议应用)

**文件**: `0004-qemu-vfio-cmask-bugfix.patch`

**修复内容**: 为 VFIO 普通迁移添加 cmask 限制

```bash
# 进入 QEMU 目录
cd /root/qemu/qemu

# 应用 patch
git apply /mnt/shared/HDBSS/HDBSS_v4_patch/DS/0004-qemu-vfio-cmask-bugfix.patch

# 验证修改
grep "vfio_pci_pre_load" hw/vfio/pci.c

# 编译 QEMU
./configure --target-list=aarch64-softmmu
make -j$(nproc)

# 部署 QEMU 到测试环境
```

**修改说明**:
```c
// hw/vfio/pci.c:2862-2875
static const VMStateDescription vmstate_vfio_pci_config = {
    .name = "VFIOPCIDevice",
    .pre_load = vfio_pci_pre_load,  // ← 添加这个回调
    ...
};

static int vfio_pci_pre_load(void *opaque)
{
    // 限制 cmask 只检查 emulated bits
    for (i = 0; i < size; i++) {
        pdev->cmask[i] &= vdev->emulated_config_bits[i];
    }
}
```

### 3.2 Debug Patch (可选，用于调试)

**文件**: `0003-qemu-vfio-config-debug.patch`

**调试内容**: VFIO config space 保存/加载、cmask 验证

```bash
# 应用 patch
git apply /mnt/shared/HDBSS/HDBSS_v4_patch/DS/0003-qemu-vfio-config-debug.patch

# 编译 QEMU

# 运行测试，debug 输出到文件
qemu-system-aarch64 ... > /tmp/qemu_debug.log 2>&1

# 或在 QEMU monitor 中查看
(qemu) info mtree
```

**关键调试点**:
- `VFIO_DEBUG_SAVE`: Config space 保存
- `VFIO_DEBUG_LOAD`: Config space 加载
- `VFIO_DEBUG_READ_0x4a`: 偏移 0x4a 读取
- `VFIO_DEBUG_VALIDATION_FAIL`: 验证失败详情

---

## 四、完整测试流程

### 4.1 准备环境

```bash
# Host A (源端)
# Host B (目标端)
# 两台机器都部署修复后的 kernel 和 QEMU
```

### 4.2 测试步骤

**第一次迁移 (A → B)**:

```bash
# Host A 启动 QEMU
qemu-system-aarch64 -machine virt ... \
-device vfio-pci,host=1d:00.1,enable-migration=on ...

# Host B 启动 QEMU (incoming)
qemu-system-aarch64 -machine virt ... \
-device vfio-pci,host=1d:00.2,enable-migration=on ... \
-incoming tcp:0:7777

# Host A 发起迁移
(qemu) migrate tcp:0:7777
```

**在 Host B 运行 workload**:

```bash
# Guest 内加载驱动
insmod /lib/modules/$(uname -r)/hisi_zip.ko uacce_mode=2

# 运行 workload
kp_utools u_accv1 -a gzip -t 1 -n compress-stream-4K ...
```

**第二次迁移 (B → A)**:

```bash
# Host B 发起迁移
(qemu) migrate tcp:0:6666

# Host A 启动 QEMU (incoming)
qemu-system-aarch64 -machine virt ... \
-device vfio-pci,host=1d:00.1,enable-migration=on ... \
-incoming tcp:0:6666

# 检查是否成功
(qemu) info status
```

### 4.3 收集 Debug 信息

```bash
# Kernel log
dmesg | grep HDBSS_DEBUG > /tmp/kernel_debug.log

# QEMU log (如果应用了 debug patch)
cat /tmp/qemu_debug.log | grep VFIO_DEBUG

# 分析关键信息
grep "VALIDATION_FAIL" /tmp/qemu_debug.log  # 验证失败
grep "DBM_DECISION" /tmp/kernel_debug.log    # DBM 决策
grep "device=1" /tmp/kernel_debug.log        # MMIO fault
```

---

## 五、验证修复效果

### 5.1 Kernel Bug Fix 验证

**检查 MMIO fault 处理**:
```bash
# Debug log 应显示:
HDBSS_DEBUG_MMIO_FAULT: Device MMIO fault detected! device=1
HDBSS_DEBUG_DBM_DECISION: device=1 enable_hdbss=1 logging_active=1
HDBSS_DEBUG_DBM_CHECK: Checking DBM condition: !device && enable_hdbss && logging_active
# 注意：没有 HDBSS_DEBUG_DBM_RESULT (因为 device=1，DBM 不添加)
```

**检查 HDBSS buffer 内容**:
```bash
# Debug log 应显示:
HDBSS_DEBUG_FLUSH_ENTRY: Marking page dirty gpa=0x... (RAM addresses)
# 注意：没有高地址 MMIO GPAs (如 0x1d...)
```

### 5.2 QEMU Bug Fix 验证

**检查 cmask 处理**:
```bash
# Debug log 应显示:
VFIO_DEBUG_LOAD_START: Loading VFIO config space, current config[0x4a]=...
# 注意：没有 VFIO_DEBUG_VALIDATION_FAIL (因为 cmask 被限制)
```

**检查验证逻辑**:
```bash
# 如果没有 VALIDATION_FAIL，说明修复成功
grep "VALIDATION_FAIL" /tmp/qemu_debug.log

# 如果仍然有失败，检查 cmask 是否被正确限制
grep "cmask" /tmp/qemu_debug.log
```

---

## 六、问题排查

### 6.1 如果仍然报错

**检查 Kernel patch 是否生效**:
```bash
# 检查源代码
cat arch/arm64/kvm/mmu.c | grep "!device && kvm->enable_hdbss"

# 应显示:
if (!device && kvm->enable_hdbss && logging_active)
    prot |= KVM_PGTABLE_PROT_DBM;
```

**检查 QEMU patch 是否生效**:
```bash
# 检查源代码
cat hw/vfio/pci.c | grep "vfio_pci_pre_load"

# 应显示:
static int vfio_pci_pre_load(void *opaque)
{
    ...
}

static const VMStateDescription vmstate_vfio_pci_config = {
    .pre_load = vfio_pci_pre_load,
    ...
};
```

### 6.2 如果 MMIO 地址仍然出现在 HDBSS buffer

**可能原因**:
- Kernel patch 未正确应用
- 内核未重新编译/部署
- 使用了旧内核

**解决方法**:
```bash
# 检查当前内核版本
uname -r

# 确认部署了新内核
# 重启测试环境加载新内核
```

### 6.3 如果仍然有 VALIDATION_FAIL

**可能原因**:
- QEMU patch 未正确应用
- emulated_config_bits 设置有问题

**解决方法**:
```bash
# 检查 QEMU 版本
qemu-system-aarch64 --version

# 确认部署了新 QEMU
# 检查 emulated_config_bits 是否正确设置 (需要更深入调试)
```

---

## 七、Patch 文件位置

所有 patch 文件位于:
```
/mnt/shared/HDBSS/HDBSS_v4_patch/DS/
```

完整文档位于:
```
/mnt/shared/HDBSS/HDBSS_v4_patch/DS/hdbss_vfio_migration_bug_summary.md
```

---

## 八、注意事项

1. **Kernel Bug Fix 是必须的** - 这是核心问题
2. **QEMU Bug Fix 是建议的** - 解决框架缺陷，防止未来类似问题
3. **Debug Patches 是可选的** - 仅用于问题分析和验证
4. **先应用 Bug Fix，再应用 Debug** - 确保 debug 信息准确
5. **测试时启用 debug logging** - 收集足够信息进行分析

---

*整理时间: 2026-05-15*