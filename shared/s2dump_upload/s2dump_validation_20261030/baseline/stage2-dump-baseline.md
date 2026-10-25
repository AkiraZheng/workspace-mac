# Stage2 Dump 主线基线测试报告（对照组）

> 用途: openEuler 内核合入 stage2 dump 功能后的对照基线。
> 本文档在主线 7.3.0-rc5（含 memattr dump patch fb59bdc757f1）上完整实测。

## 1. 测试环境

| 项 | 值 |
|----|----|
| 宿主机 | 192.168.90.60, 鲲鹏920, 80核/61G, openEuler 24.03 SP3 |
| 宿主内核 | 7.3.0-rc5 (v7.3-rc5 + fb59bdc757f1 "KVM: arm64: ptdump: Dump stage-2 memory attributes", rpm -4) |
| FWB 状态 | HCR_EL2.FWB=1 (dmesg: Stage-2 Force Write-Back) |
| QEMU | 8.2, -machine virt,accel=kvm -cpu host -smp 4 -m 4G |
| 虚机镜像 | openEuler-24.03-LTS-aarch64.qcow2, guest内核 6.6.0-28.0.0.34.oe2403 |
| 直通设备 | 0000:31:00.0 HiSilicon ZIP Engine (19e5:a250), -device vfio-pci |
| dump 接口 | /sys/kernel/debug/kvm/<pid>-<fd>/{stage2_page_tables,stage2_levels,ipa_range} |
| 结构参数 | stage2_levels=3, ipa_range=43 (IPA空间 2^43) |

## 2. 验证项结论总表

| 编号 | 验证点 | 结论 |
|------|--------|------|
| T-IF-01 | VM创建后文件集合(0400 root) | PASS |
| T-IF-02 | VM销毁后 <pid>-<fd> 目录清理 | PASS (7583-9/9544-9/10329-8 三次验证) |
| T-IF-03 | 多VM目录隔离 | PASS (9544-9 与 10329-8 并存) |
| T-IF-04 | 表头 ---[ Guest IPA ]--- | PASS |
| T-IF-05 | 行格式 0xstart-0xend size+unit level flags | PASS |
| T-GE-01 | stage2_levels=3 | PASS |
| T-GE-02 | ipa_range=43 | PASS |
| T-GE-03 | 区间无缝衔接(全dump脚本校验) | PASS (7/7份) |
| T-GE-04 | 覆盖上界 end==2^43==0x0000080000000000 | PASS (7/7份) |
| T-GE-05 | 层级粒度几何(L1=1G/L2=2M/L3=4K整倍数) | PASS (7/7份) |
| T-PR-01 | 未映射区间无任何flags(prot==0跳过dump_prot) | PASS |
| T-PR-02 | R/W 权限组合 | PASS |
| T-PR-03 | XN组合 px ux/PXNux/PXNUXN/px UXN | PASS (px ux 与 PXNUXN 实测) |
| T-PR-04 | AF 位 | PASS |
| T-PR-05 | BLK 与层级互斥(L3无BLK) | PASS |
| T-PR-06 | memattr WB (FWB编码6) | PASS (guest RAM) |
| T-PR-07 | memattr NC (编码5) | PASS (VFIO直通BAR) |
| T-PR-08 | memattr DEV (编码1) | 无法触发(登记): KVM不支持GICv2 emulation; vfio PCI mmap 设 VM_ALLOW_ANY_UNCACHED 恒走 NC |
| T-PR-09 | memattr 不匹配时静默(clear=NULL) | PASS |
| T-DY-01 | 映射随启动增长/回收 | PASS (A-early 30行 -> A-stable 26行) |
| T-DY-02 | 稳态可重复性(双cat diff为空) | PASS |
| T-DY-03 | 懒映射: 直通BAR在guest PCI枚举期即出现 | PASS (B1早期4M NC) |
| T-DY-04 | 并发安全(VM运行中采集无死锁) | PASS |
| T-DY-05 | block聚变: 队列活动填充2M洞 | PASS (C-held: 116M+2M洞+56M -> 174M) |

## 3. 场景矩阵与对比数据

| 场景 | 配置 | 行数 | WB | NC | 直通BAR区间 | 备注 |
|------|------|------|----|----|-------------|------|
| A-early | virtio-only, 启动16s | 30 | 12 | 0 | 无 | 启动初期临时映射多 |
| A-stable | virtio-only, 稳态 | 26 | 10 | 0 | 无 | 临时映射回收后行数减少 |
| B1-early | +VFIO, 启动16s | 27 | 9 | 1 | 4M NC PXNUXN | BAR懒映射早期已现(guest PCI枚举接触) |
| B2-nodrv | +VFIO, guest无驱动稳态 | 27 | 9 | 1 | 4M NC | 与B1仅RAM区2M/4M边界微调 |
| C-drv | B2+驱动加载+uacce就绪 | 27 | 9 | 1 | 4M NC | 驱动加载不改变S2(等价B2) |
| C-held | C+uacce队列mmap持有中 | 25 | 9 | 1 | 4M NC | 2M洞被队列分配填充,三区间聚合174M |
| minivm | 极简无盘VM(512M,无vfio) | 15 | 5 | 0 | 无 | 最小VM基线,仅RAM映射 |

### 关键差异规律 (openEuler 侧必须重现)

1. 无直通时 NC 恒为 0; 直通后 0x8000000000 高址窗出现 NC 区间 (PXNUXN AF BLK NC)
2. 直通 BAR 区间在 guest PCI 枚举期(启动~16s)即已建立, 与驱动加载/业务无关
3. 驱动加载 (hisi_zip probe) 与 uacce 设备就绪不改变 S2 dump
4. uacce 队列 mmap 触发的分配可填充 RAM 中 2M 未映射洞 -> 与邻区聚合
5. 未映射大区间无 flags 输出 (基线行为, 非打印 F)
6. 末行恒为 0x...-0x0000080000000000 (2^43 上界)

## 4. 核心 dump 快照

### 4.1 A-stable (virtio-only 稳态)
---[ Guest IPA ]---
0x0000000000000000-0x0000000009000000         144M 2
0x0000000009000000-0x00000000090a0000         640K 3
0x00000000090a0000-0x00000000090a1000           4K 3   R W px ux  AF     WB
0x00000000090a1000-0x0000000009200000        1404K 3
0x0000000009200000-0x0000000040000000         878M 2
0x0000000040000000-0x0000000043200000          50M 2   R W px ux  AF BLK WB
0x0000000043200000-0x0000000048000000          78M 2
0x0000000048000000-0x000000004a200000          34M 2   R W px ux  AF BLK WB
0x000000004a200000-0x0000000080000000         862M 2
0x0000000080000000-0x00000000c0000000           1G 1
0x00000000c0000000-0x00000000fbe00000         958M 2
0x00000000fbe00000-0x0000000102000000          98M 2   R W px ux  AF BLK WB
0x0000000102000000-0x0000000102200000           2M 2
0x0000000102200000-0x0000000103600000          20M 2   R W px ux  AF BLK WB
0x0000000103600000-0x0000000103a00000           4M 2
0x0000000103a00000-0x0000000107c00000          66M 2   R W px ux  AF BLK WB
0x0000000107c00000-0x0000000108200000           6M 2
0x0000000108200000-0x0000000109a00000          24M 2   R W px ux  AF BLK WB
0x0000000109a00000-0x0000000109c00000           2M 2
0x0000000109c00000-0x000000010b600000          26M 2   R W px ux  AF BLK WB
0x000000010b600000-0x000000010bc00000           6M 2
0x000000010bc00000-0x0000000112a00000         110M 2   R W px ux  AF BLK WB
0x0000000112a00000-0x000000013b800000         654M 2
0x000000013b800000-0x0000000140000000          72M 2   R W px ux  AF BLK WB
0x0000000140000000-0x0000080000000000        8187G 1

### 4.2 B2-nodrv (VFIO直通, guest无驱动稳态)
---[ Guest IPA ]---
0x0000000000000000-0x0000000009000000         144M 2
0x0000000009000000-0x00000000090a0000         640K 3
0x00000000090a0000-0x00000000090a1000           4K 3   R W px ux  AF     WB
0x00000000090a1000-0x0000000009200000        1404K 3
0x0000000009200000-0x0000000040000000         878M 2
0x0000000040000000-0x0000000043200000          50M 2   R W px ux  AF BLK WB
0x0000000043200000-0x0000000048000000          78M 2
0x0000000048000000-0x000000004a200000          34M 2   R W px ux  AF BLK WB
0x000000004a200000-0x0000000080000000         862M 2
0x0000000080000000-0x00000000c0000000           1G 1
0x00000000c0000000-0x00000000fbe00000         958M 2
0x00000000fbe00000-0x0000000103200000         116M 2   R W px ux  AF BLK WB
0x0000000103200000-0x0000000103400000           2M 2
0x0000000103400000-0x0000000106c00000          56M 2   R W px ux  AF BLK WB
0x0000000106c00000-0x0000000107200000           6M 2
0x0000000107200000-0x000000010a600000          52M 2   R W px ux  AF BLK WB
0x000000010a600000-0x000000010a800000           2M 2
0x000000010a800000-0x0000000110800000          96M 2   R W px ux  AF BLK WB
0x0000000110800000-0x0000000110a00000           2M 2
0x0000000110a00000-0x0000000112c00000          34M 2   R W px ux  AF BLK WB
0x0000000112c00000-0x000000013b800000         652M 2
0x000000013b800000-0x0000000140000000          72M 2   R W px ux  AF BLK WB
0x0000000140000000-0x0000008000000000         507G 1
0x0000008000000000-0x0000008000400000           4M 2   R W PXNUXN AF BLK NC
0x0000008000400000-0x0000008040000000        1020M 2
0x0000008040000000-0x0000080000000000        7679G 1

### 4.3 C-uacce-held (uacce non-SVA 队列mmap持有中)
差异行 (对比 B2): 0xfbe00000-0x106c00000 174M R W px ux AF BLK WB
(原 B2 为 116M WB + 2M未映射 + 56M WB 三段, 队列分配填充2M洞后聚合)
---[ Guest IPA ]---
0x0000000000000000-0x0000000009000000         144M 2
0x0000000009000000-0x00000000090a0000         640K 3
0x00000000090a0000-0x00000000090a1000           4K 3   R W px ux  AF     WB
0x00000000090a1000-0x0000000009200000        1404K 3
0x0000000009200000-0x0000000040000000         878M 2
0x0000000040000000-0x0000000043200000          50M 2   R W px ux  AF BLK WB
0x0000000043200000-0x0000000048000000          78M 2
0x0000000048000000-0x000000004a200000          34M 2   R W px ux  AF BLK WB
0x000000004a200000-0x0000000080000000         862M 2
0x0000000080000000-0x00000000c0000000           1G 1
0x00000000c0000000-0x00000000fbe00000         958M 2
0x00000000fbe00000-0x0000000106c00000         174M 2   R W px ux  AF BLK WB
0x0000000106c00000-0x0000000107200000           6M 2
0x0000000107200000-0x000000010a600000          52M 2   R W px ux  AF BLK WB
0x000000010a600000-0x000000010a800000           2M 2
0x000000010a800000-0x0000000110800000          96M 2   R W px ux  AF BLK WB
0x0000000110800000-0x0000000110a00000           2M 2
0x0000000110a00000-0x0000000112c00000          34M 2   R W px ux  AF BLK WB
0x0000000112c00000-0x000000013b800000         652M 2
0x000000013b800000-0x0000000140000000          72M 2   R W px ux  AF BLK WB
0x0000000140000000-0x0000008000000000         507G 1
0x0000008000000000-0x0000008000400000           4M 2   R W PXNUXN AF BLK NC
0x0000008000400000-0x0000008040000000        1020M 2
0x0000008040000000-0x0000080000000000        7679G 1

### 4.4 minivm (极简无盘VM, 512M内存)
---[ Guest IPA ]---
0x0000000000000000-0x0000000009000000         144M 2
0x0000000009000000-0x00000000090a0000         640K 3
0x00000000090a0000-0x00000000090a1000           4K 3   R W px ux  AF     WB
0x00000000090a1000-0x0000000009200000        1404K 3
0x0000000009200000-0x0000000040000000         878M 2
0x0000000040000000-0x0000000043600000          54M 2   R W px ux  AF BLK WB
0x0000000043600000-0x0000000043800000           2M 2
0x0000000043800000-0x0000000047c00000          68M 2   R W px ux  AF BLK WB
0x0000000047c00000-0x0000000048000000           4M 2
0x0000000048000000-0x000000004a400000          36M 2   R W px ux  AF BLK WB
0x000000004a400000-0x000000005b400000         272M 2
0x000000005b400000-0x0000000060000000          76M 2   R W px ux  AF BLK WB
0x0000000060000000-0x0000000080000000         512M 2
0x0000000080000000-0x0000080000000000        8190G 1

### 4.5 B1-early 与 B2 差异 (RAM 区边界微调示例)
```
< 0x0000000103200000-0x0000000103600000    4M 2          (B1未映射)
> 0x0000000103200000-0x0000000103400000    2M 2          (B2未映射,边界移动)
< 0x0000000103600000-0x0000000106c00000   54M 2  R W px ux AF BLK WB
> 0x0000000103400000-0x0000000106c00000   56M 2  R W px ux AF BLK WB
```

## 5. 关键观察记录

1. **NC 的来源**: VFIO 直通 BAR 经 QEMU memslot (host WC mmap, vfio_pci_core.c 设
   VM_ALLOW_ANY_UNCACHED) -> KVM S2 跟随 host pgprot 给 NORMAL_NC。
   模拟设备 BAR (virtio) 走普通内存 = WB。memattr 标签可清晰区分两者。
2. **DEV 不可触发**: mmu.c 的 device 分支需要无 VM_ALLOW_ANY_UNCACHED 的
   uncached vma; kvm_phys_addr_ioremap 唯一调用者是 GICv2 GICV (vgic-v2.c:459),
   本平台 KVM 不支持 GICv2 emulation。判定为环境性不可达, 非功能缺陷。
3. **未映射区间行为**: note_page 对 current_prot==0 直接跳过 dump_prot,
   行内无任何 flags (含 F)。openEuler 实现若打印 F 即为行为偏差。
4. **2M 洞填充聚合** (C-held): uacce 队列分配落在 0x103200000-0x10340000 区间,
   映射建立后与两侧同属性 WB 区间聚合为单行 174M。体现了 dump 的区间聚合语义。

## 6. openEuler 对照执行方法

1. 同机部署 openEuler 合入内核, 保持 QEMU 命令行/镜像/直通设备完全一致
2. 按场景矩阵顺序复现 A/B/C (脚本: pkill qemu-system-aar 后分别运行
   /home/zt/vm-bootkit/start-vm.sh 与 start-vm-vfio.sh)
3. 采集命令: cat /sys/kernel/debug/kvm/<pid>-<fd>/stage2_page_tables
4. 用 /tmp/check-ge.sh 的逻辑做 T-GE-03/04/05 脚本校验

### 判定标准

| 层级 | 项 | 标准 |
|------|-----|------|
| 硬性一致(必须相同) | T-IF 全部, T-GE-01~04, T-PR 语义 | 不一致 = 合入有误 |
| 语义一致(数值可差) | 具体区间划分/行数/T-DY 数据 | 依赖运行时映射历史 |
| 登记差异(预期) | memattr 标签(若仅合入原生ptdump), 未映射行行为若打印F | 对照组已知差异 |

## 7. 原始数据索引

| 文件 | 说明 |
|------|------|
| /home/zt/baseline-data/A-early.txt | 场景A启动16s (30行) |
| /home/zt/baseline-data/A-stable-1.txt / -2.txt | 场景A稳态双采(可重复性验证) |
| /home/zt/baseline-data/B1-early.txt | 场景B启动16s (27行) |
| /home/zt/baseline-data/B2-nodrv.txt | 场景B无驱动稳态 (27行) |
| /home/zt/baseline-data/C-drv.txt | 场景C驱动加载后(等价B2) |
| /home/zt/baseline-data/C-uacce-held.txt | 场景C队列持有中 (25行) |
| /home/zt/baseline-data/minivm.txt | 极简VM基线 (15行) |
| /home/zt/baseline-data/A-meta.txt / B-meta.txt | levels/ipa_range |

本基线由主线 7.3.0-rc5 + fb59bdc757f1 实测生成 (2026-10-29)。
