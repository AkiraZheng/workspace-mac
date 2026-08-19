# HDBSS v5 测试指南

## 1. 编译（编译机）

### 1.1 编译内核

```bash
cd /root/code/linux/linux
make ARCH=arm64 -j$(nproc)
```

### 1.2 安装内核头文件（selftests 依赖）

```bash
make ARCH=arm64 headers_install
```

### 1.3 编译 KVM selftests

```bash
cd tools/testing/selftests/kvm
make ARCH=arm64 arm64/hdbss_test dirty_log_test
```

### 1.4 编译 QEMU

```bash
cd /root/code/openeuler_qemu/qemu
./configure --target-list=aarch64-softmmu --enable-kvm
make -j$(nproc)
```

## 2. 部署到单板

单板需要运行编译好的带 HDBSS patch 的内核。selftests 二进制直接拷贝即可，不需要 guest kernel Image。

```bash
# 拷贝 selftests 到单板
scp tools/testing/selftests/kvm/arm64/hdbss_test <board>:/tmp/
scp tools/testing/selftests/kvm/dirty_log_test <board>:/tmp/

# 拷贝 QEMU 到单板（如需端到端测试）
scp build/qemu-system-aarch64 <board>:/usr/local/bin/
```

## 3. 运行测试（单板）

### 3.1 HDBSS ioctl 接口测试

验证 `KVM_CAP_ARM_HDBSS_BUFFER_SIZE` 的接口行为，不需要跑 guest：

```bash
/tmp/hdbss_test
```

测试项：

| # | 测试内容 | 预期结果 |
|---|---------|---------|
| 1 | 全局 CHECK_EXTENSION | 返回 max buffer size (SZ_2M = 2097152) |
| 2 | per-VM CHECK_EXTENSION（未配置） | 返回默认值 (SZ_4K = 4096) |
| 3 | per-VM CHECK_EXTENSION（配置后） | 返回配置值 |
| 4 | ENABLE_CAP 设置合法值 [SZ_4K, SZ_2M] | 成功 (0) |
| 5 | ENABLE_CAP 设置 0 | -EINVAL |
| 6 | ENABLE_CAP 设置非 2 的幂 | -EINVAL |
| 7 | ENABLE_CAP 设置 < SZ_4K | -EINVAL |
| 8 | ENABLE_CAP 设置 > SZ_2M | -EINVAL |
| 9 | vCPU 创建后设置 | -EINVAL |
| 10 | 重复设置 | -EBUSY |
| 11 | dirty ring 已设后设 HDBSS | -EINVAL |

### 3.2 Dirty tracking 功能测试

验证 HDBSS 透明工作的功能正确性，需要创建 VM、跑 vCPU：

```bash
# dirty-bitmap 模式 + HDBSS
/tmp/dirty_log_test -M dirty-log

# dirty-ring 模式 + HDBSS（验证共存）
/tmp/dirty_log_test -M dirty-ring

# 指定 dirty ring size（验证 reservation 机制）
/tmp/dirty_log_test -M dirty-ring -c 4096

# 所有模式（dirty-log + clear-log + dirty-ring）
/tmp/dirty_log_test

# 指定迭代次数和间隔
/tmp/dirty_log_test -i 64 -I 10
```

HDBSS 对用户透明：dirty logging 开启时自动启用，不需要额外配置。
如果 HDBSS 有 bug（如 flush 丢失脏页、buffer overflow），
`dirty_log_test` 的 `vm_dirty_log_verify()` 会 assert 失败。

### 3.3 QEMU 端到端测试

用 QEMU 起虚机 + live migration 验证端到端正确性：

```bash
# 配置 HDBSS buffer size（entries 为单位，512 = 4KB buffer）
qemu-system-aarch64 -accel kvm,hdbss-buffer-size=512 \
    -m 1G -smp 2 -cpu host \
    -drive file=guest.img,if=virtio

# 不配 HDBSS（用 kernel 默认 PAGE_SIZE）
qemu-system-aarch64 -accel kvm \
    -m 1G -smp 2 -cpu host \
    -drive file=guest.img,if=virtio

# dirty ring 模式（HDBSS buffer size 由 kernel 自动计算）
qemu-system-aarch64 -accel kvm,dirty-ring-size=4096 \
    -m 1G -smp 2 -cpu host \
    -drive file=guest.img,if=virtio
```

> **注意**：`hdbss-buffer-size` 和 `dirty-ring-size` 互斥，不能同时设置。

## 4. 测试矩阵

| 场景 | HDBSS buffer | dirty ring | 命令 |
|------|-------------|-----------|------|
| bitmap + 默认 buffer | 不配 | 不配 | `dirty_log_test -M dirty-log` |
| bitmap + 自定义 buffer | 512 entries | 不配 | `hdbss_test` 验证 ioctl |
| dirty ring + 自动 buffer | 不配 | 4096 entries | `dirty_log_test -M dirty-ring -c 4096` |
| dirty ring + 最小 ring | 不配 | 576 entries | `dirty_log_test -M dirty-ring -c 576` |
| dirty ring + 大 ring | 不配 | 65536 entries | `dirty_log_test -M dirty-ring -c 65536` |

## 5. 注意事项

- 所有测试需要 HDBSS 硬件支持（FEAT_HDBSS）
- 不支持 HDBSS 的硬件上 `hdbss_test` 自动 skip
- `dirty_log_test` 在不支持 HDBSS 的硬件上也能跑（回退到软件 dirty tracking）
- dirty ring 最小 size 受 HDBSS reservation 影响：
  - rsvd = 64 + 512 = 576 entries
  - 最小 dirty_ring_size = 576 entries = 9216 bytes
