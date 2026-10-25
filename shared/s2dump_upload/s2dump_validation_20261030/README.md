# openEuler Stage-2 Dump 验证与提交材料包

> 归档日期: 2026-10-30 | 分支: `merge/origin_linux-20261024-203357`（基于 openEuler OLK-6.6）
> 功能: KVM arm64 guest stage-2 页表 dump（9 个主线回合 patch + 1 个自研 memattr patch）

## 目录结构

```
├── patches/                    # 提交用 patch 序列（10 个，openEuler 惯例格式，可直接 git am）
│   ├── 0001~0009               #   主线回合：mainline inclusion 头 + Reference + Conflicts 注记
│   └── 0010                    #   自研 memattr：hulk inclusion 头（作者/SoB: Tian Zheng）
├── baseline/                   # 对照组：主线基线（v7.3-rc5 + fb59bdc757f1 实测）
│   ├── stage2-dump-baseline.md    # 基线测试方法文档（25 项验证定义 + 判定标准，见 §6 执行方法）
│   └── baseline-data/             # 主线原始 dump 数据（A/B/C/minivm 场景）
├── test-scripts/               # 测试脚本（板 192.168.90.60 实际使用）
│   ├── collect.sh                 # dump 采集：自动发现 /sys/kernel/debug/kvm/<pid>-<fd>/
│   ├── check-ge.sh                # T-GE-03/04/05 机械校验（衔接/上界/粒度）
│   ├── holder.c                   # uacce 队列 mmap 持有程序源码（场景 C-held）
│   └── vm-bootkit/
│       ├── start-vm.sh            # 场景 A/B 虚机启动（virtio-only）
│       ├── start-vm-vfio.sh       # 场景 B/C 虚机启动（0000:31:00.0 ZIP 直通）
│       └── vfio-zip-nonsva-test.md  # 直通测试方案（含 guest 内 uacce_mode=2 加载步骤）
├── test-data/                  # openEuler 侧采集数据
│   ├── olk-data/                  # 8 份 dump（A-early/A-stable-1,2/B1-early/B2-nodrv/C-drv/C-uacce-held/minivm）
│   └── olk-evidence/              # meta 值 / debugfs 权限 / 多 VM 隔离 / GICv2 尝试记录
└── reports/
    └── olk-s2dump-compare-report.md  # 25 项对照结论：硬性一致 18/18，语义一致 6/6，无不一致
```

## 测试环境要点

- 板卡: 192.168.90.60（鲲鹏 920, 80 核/61G, openEuler 24.03 SP3），内核 `6.6.0-s2dump`（RPM: kernel-6.6.0_s2dump-2）
- 被测内核 config: 库存 `config-6.6.0-132.0.0.111.oe2403sp3` + `CONFIG_PTDUMP_STAGE2_DEBUGFS=y`
- QEMU: `-machine virt,accel=kvm -cpu host -smp 4 -m 4G`；guest: openEuler-24.03-LTS qcow2（内核 6.6.0-28.0.0.34）
- 直通设备: `0000:31:00.0` HiSilicon ZIP Engine (19e5:a250)，vfio-pci
- **未归档的大文件**: qcow2 镜像 / vmlinuz / initramfs.img（可经 `vfio-zip-nonsva-test.md` §7 与板上 `skill-scripts/download-image.sh`、`extract-kernel.sh` 重新获取）

## 已知事项

1. **bugzilla 占位**: patches 中 `https://atomgit.com/openeuler/kernel/issues/XXX` 为占位符，建单后需统一替换（生成脚本参数化，替换代价约 1 分钟）。
2. **登记差异（唯一）**: XN 字段渲染——主线（FEAT_XNX 演进后）打 `px ux/PXNUXN`，本系列打 `x/NX`，语义等价（详见 compare-report §4）。
3. **T-PR-08（DEV memattr）**: 两侧同因不可达（板卡 ACPI 无 GICV resource，KVM 不支持 GICv2 emulation），与基线登记一致。
4. **脱敏说明**: vm-bootkit 脚本与文档中的虚机登录密码已替换为 `VM_PASSWORD` 占位符（与仓库既有脱敏惯例一致，实际值见测试板环境）。

## PR 描述用的 XN 声明（系列范围说明，非 commit message）

> 本系列暂不涉及嵌套虚拟化页表的 dump，故未合入上游 FEAT_XNX 的 XN 字段实现：stage-2 的 XN 字段仍打印为单一 NX 标签。后续若需要导出嵌套 guest 的 XN 权限信息，可在本系列基础上继续合入以下 commit：
>
> - `dc31124379b6` arm64: Detect FEAT_XNX
> - `2608563b466b` KVM: arm64: Add support for FEAT_XNX stage-2 permissions
> - `d93febe2ed2e` KVM: arm64: nv: Forward FEAT_XNX permissions to the shadow stage-2
> - `6b49f70022ed` KVM: arm64: Teach ptdump about FEAT_XNX permissions

英文版:

> Nested virtualization page table dumping is out of scope for this series, so the upstream FEAT_XNX implementation of the XN field is deliberately left out: the stage-2 XN field is still printed as a single NX label. If exporting nested guest XN permissions is needed later, the following commits can be merged on top: dc31124379b6 / 2608563b466b / d93febe2ed2e / 6b49f70022ed.
