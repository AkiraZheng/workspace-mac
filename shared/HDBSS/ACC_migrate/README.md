# HDBSS VFIO Migration Bug - Patch 使用指南

## 一、Patch 文件列表

已通过 `git format-patch` 生成的标准 patch 文件：

| 序号 | 文件名 | 类型 | 描述 |
|------|--------|------|------|
| 0001 | `0001-kernel-hdbss-mmio-bugfix.patch` | **Bug Fix** | Kernel: 修复 DBM 用于 MMIO 的 bug（必须应用） |
| 0002 | `0002-KVM-arm64-Add-HDBSS-debug-logging.patch` | Debug | Kernel: HDBSS + VFIO MMIO 调试日志（可选） |
| 0003 | `0003-qemu-vfio-cmask-bugfix.patch` | **Bug Fix** | QEMU: 限制 cmask 验证范围（建议应用） |

---

## 二、问题根本原因

**双重 Bug**：

1. **Kernel Bug**：HDBSS 给 VFIO MMIO 区域错误添加 DBM 位
   - 影响：VFIO MMIO 访问异常 → 设备状态不一致
   - 修复：添加 `!device` 检查，防止 DBM 用于 MMIO

2. **QEMU Bug**：VFIO 普通迁移缺少 cmask 限制机制
   - 影响：硬件只读位验证失败 → 迁移报错
   - 修复：添加 `pre_load` 回调，限制 cmask 只检查模拟位

---

## 三、Patch 应用方法

### 3.1 Kernel Patch 应用

**Bug Fix Patch (必须应用)**：

```bash
cd /path/to/kernel
git am /mnt/shared/HDBSS/ACC_migrate/0001-kernel-hdbss-mmio-bugfix.patch

# 验证应用成功
git log --oneline -1
# 应显示: Fix HDBSS DBM incorrectly applied to VFIO MMIO regions

# 编译内核
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc)

# 部署到测试环境
```

**Debug Patch (可选，用于调试)**：

```bash
git am /mnt/shared/HDBSS/ACC_migrate/0002-KVM-arm64-Add-HDBSS-debug-logging.patch

# 编译并部署

# 启用 kernel log
echo 8 > /proc/sys/kernel/printk

# 测试后收集 log
dmesg | grep "HDBSS_DEBUG" > /tmp/kernel_hdbss_debug.log
```

### 3.2 QEMU Patch 应用

**Bug Fix Patch (建议应用)**：

```bash
cd /path/to/qemu
git am /mnt/shared/HDBSS/ACC_migrate/0003-qemu-vfio-cmask-bugfix.patch

# 验证应用成功
git log --oneline -1
# 应显示: Add pre_load callback to limit cmask for normal migration

# 编译 QEMU
./configure --target-list=aarch64-softmmu
make -j$(nproc)

# 部署到测试环境
```

---

## 四、验证修复效果

### 4.1 Kernel Bug Fix 验证

**检查源码修改**：

```bash
grep "!device && kvm->enable_hdbss" arch/arm64/kvm/mmu.c
# 应显示: if (!device && kvm->enable_hdbss && logging_active)
```

**检查 MMIO 处理**：

```bash
# 应用 debug patch 后
dmesg | grep "HDBSS_DEBUG_DBM_SKIP"
# 应显示: DBM NOT added for MMIO (device=1)
```

**检查 HDBSS buffer**：

```bash
dmesg | grep "HDBSS_DEBUG_FLUSH_ENTRY"
# 应只显示 RAM GPA，无 MMIO GPA
```

### 4.2 QEMU Bug Fix 验证

**检查源码修改**：

```bash
grep "vfio_pci_pre_load" hw/vfio/pci.c
# 应显示函数定义和 pre_load = vfio_pci_pre_load
```

**检查迁移验证**：

```bash
# 运行两次迁移测试
# 应无 "Bad config data" 报错
```

---

## 五、完整测试流程

### 5.1 准备环境

**Host A (源端) 和 Host B (目标端)** 都部署：
- 修复后的 kernel
- 修复后的 QEMU

### 5.2 第一次迁移 (A → B)

```bash
# Host A 启动 VM + VFIO
qemu-system-aarch64 -machine virt ... \
  -device vfio-pci,host=1d:00.1,enable-migration=on ...

# Host B 启动 VM (incoming)
qemu-system-aarch64 ... -incoming tcp:0:7777

# Host A 发起迁移
(qemu) migrate tcp:0:7777
```

### 5.3 Workload 运行

```bash
# Guest 内运行 hisi_zip workload
insmod hisi_zip.ko uacce_mode=2
kp_utools u_accv1 -a gzip -t 1 ...
```

### 5.4 第二次迁移 (B → A)

```bash
# Host B 发起迁移
(qemu) migrate tcp:0:6666

# Host A 启动 VM (incoming)
qemu-system-aarch64 ... -incoming tcp:0:6666

# 检查结果 - 应成功无报错
(qemu) info status
```

---

## 六、Debug 信息收集

### 6.1 Kernel Debug (如果应用了 debug patch)

```bash
# 启用 kernel log
echo 8 > /proc/sys/kernel/printk

# 运行测试

# 收集 log
dmesg | grep "HDBSS_DEBUG" > /tmp/kernel_debug.log

# 分析关键信息
grep "MMIO_FAULT" /tmp/kernel_debug.log     # MMIO fault 检测
grep "DBM_DECISION" /tmp/kernel_debug.log   # DBM 决策
grep "DBM_SKIP" /tmp/kernel_debug.log       # DBM 是否跳过
grep "FLUSH_ENTRY" /tmp/kernel_debug.log    # 脏页 GPA
```

### 6.2 EVB vs FPGA 对比

**关键对比项**：

```bash
# 对比 MMIO fault 处理
grep "device=1" evb_debug.log | wc -l
grep "device=1" fpga_debug.log | wc -l

# 对比 DBM 决策
grep "DBM_RESULT" evb_debug.log | wc -l
grep "DBM_RESULT" fpga_debug.log | wc -l

# 对比 HDBSS buffer 内容
grep "gpa=0x1d" evb_debug.log | wc -l  # MMIO GPA 出现次数
grep "gpa=0x1d" fpga_debug.log | wc -l
```

---

## 七、Patch 文件内容说明

### 7.1 0001-kernel-hdbss-mmio-bugfix.patch

**修改文件**: `arch/arm64/kvm/mmu.c`

**修改内容**: 第 1689 行添加 `!device` 检查

```c
#ifdef CONFIG_ARM64_HDBSS
-    if (kvm->enable_hdbss && logging_active)
+    if (!device && kvm->enable_hdbss && logging_active)
        prot |= KVM_PGTABLE_PROT_DBM;
#endif
```

**原理**: DBM 只应该用于 RAM 内存，不用于 Device/MMIO 内存

### 7.2 0002-KVM-arm64-Add-HDBSS-debug-logging.patch

**修改文件**: 
- `arch/arm64/kvm/mmu.c`
- `arch/arm64/kvm/handle_exit.c`
- `arch/arm64/kvm/arm.c`

**新增 Debug 打印**:
- `HDBSS_DEBUG_MMIO_FAULT`: MMIO fault 检测
- `HDBSS_DEBUG_DBM_DECISION`: DBM 决策条件
- `HDBSS_DEBUG_DBM_RESULT/SKIP`: DBM 是否添加
- `HDBSS_DEBUG_FLUSH_ENTRY`: HDBSS buffer 脏页 GPA
- `HDBSS_DEBUG_ENABLE/DISABLE`: HDBSS 启用/禁用

### 7.3 0003-qemu-vfio-cmask-bugfix.patch

**修改文件**: `hw/vfio/pci.c`

**新增内容**: `vfio_pci_pre_load` 函数和 `pre_load` 回调

```c
static int vfio_pci_pre_load(void *opaque)
{
    // 限制 cmask 只检查 emulated bits
    for (i = 0; i < size; i++) {
        pdev->cmask[i] &= vdev->emulated_config_bits[i];
    }
    return 0;
}

static const VMStateDescription vmstate_vfio_pci_config = {
    .pre_load = vfio_pci_pre_load,  // 新增
    ...
};
```

**原理**: 硬件只读位不应该强制验证，允许自然不一致

---

## 八、注意事项

1. **Patch 应用顺序**: 0001 → 0002 → 0003 (按序号依次应用)
2. **Kernel Bug Fix 是必须的** - 核心问题修复
3. **QEMU Bug Fix 是建议的** - 解决框架缺陷
4. **Debug Patch 是可选的** - 用于问题分析和验证
5. **必须重新编译和部署** - Patch 应用后生效
6. **建议在两个平台都测试** - 验证修复有效性

---

## 九、故障排查

### 9.1 Patch 应用失败

```bash
# 检查 patch 格式
cat /mnt/shared/HDBSS/ACC_migrate/0001-kernel-hdbss-mmio-bugfix.patch

# 尝试手动应用
patch -p1 < /mnt/shared/HDBSS/ACC_migrate/0001-kernel-hdbss-mmio-bugfix.patch

# 或者检查 git 状态
git status
```

### 9.2 编译失败

```bash
# 检查源码修改是否正确
git diff HEAD

# 检查修改位置
grep "!device && kvm->enable_hdbss" arch/arm64/kvm/mmu.c
```

### 9.3 测试仍然失败

**可能原因**:
- Kernel/QEMU 未重新部署
- 使用了旧版本
- 其他环境问题

**解决方法**:
- 确认内核版本: `uname -r`
- 确认 QEMU 版本: `qemu-system-aarch64 --version`
- 收集 debug log 分析

---

## 十、文档位置

**Patch 文件**: `/mnt/shared/HDBSS/ACC_migrate/`

**相关文档**:
- `hdbss_vfio_migration_bug_summary.md` - Bug 总结报告
- `debug_flow_updated.md` - Debug 流程详解
- `README.md` - 本使用指南

---

*生成时间: 2026-05-16*
*使用 git format-patch 生成标准 patch 格式*