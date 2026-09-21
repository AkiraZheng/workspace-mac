# SMMUv3 `accel=on` 热迁移 RFC 测试计划

> 测试对象:[RFC PATCH 0/7] hw/arm/smmuv3: Live migration for accel=on
> 作者:Shameer Kolothum <skolothumtho@nvidia.com>,2026-09-04 发 qemu-devel
> 测试设备:海思加速器 VF(VFIO 可迁移)
> 目的:真机验证后向社区回复 Tested-by

---

## 0. 一页速览

| 问题 | 答案 |
|---|---|
| 测什么 | vSMMU(内核加速嵌套翻译,无 IOPF)+ vfio-pci 海思加速器的整机热迁移 |
| QEMU 要哪些 patch | 基线 `99e54ab5e7` + `patches/qemu/0001~0008`(7 个 RFC + 1 个 pci fix) |
| 内核要不要改 | **不改代码**:用作者分支 `iommu_pt_arm64_s2_dbm`;只做 config + 平台启动验证 |
| 三个硬门槛 | ①作者内核能在服务器启动 ②宿主机 SMMUv3 有 HTTU/DBM ③加速器 QM V4/V5 |
| 最关键用例 | TC4:设备持续写内存 + 迁移 → 数据完整性(海思设备无自跟踪脏页,全靠 patch 6) |
| 产出 | 逐封回复 7 个 patch 邮件的 Tested-by(模板见 §7) |

---

## 1. 测试代码与来源

| 项目 | 内容 |
|---|---|
| 本地 QEMU 代码 | `/home/akira/code/qemu/qemu`,分支 `smmuv3-accel-live-migrn-rfcv1` |
| QEMU 基线 | upstream master `99e54ab5e7`(2026-09-03,"Merge tag 'hw-misc-20260903'") |
| 内容 | 基线 + 7 个邮件 patch(b4 mbox,`git am` 干净应用)+ 1 个额外提交 |
| 树校验 | 与作者分支 tip `git diff` 为空(逐字节一致),测的就是作者发布的代码 |

**⚠️ 第 8 个提交不在邮件系列里**:作者分支上多一个
`pci/pcie: Do not check Link Status 2 across a migration`
——修复 vfio-pci 设备在 pcie-root-port 下迁移时 Link Status 2 的 Flit Mode 位两端不一致
(同型号两张卡都会不一致,与双机无关)。**测试必须包含**,本分支已 cherry-pick。

分支复现(备忘):

```bash
git switch -c smmuv3-accel-live-migrn-rfcv1 99e54ab5e7
git am 20260904_skolothumtho_hw_arm_smmuv3_live_migration_for_accel_on.mbx
git fetch https://github.com/shamiali2008/qemu-master.git smmuv3-accel-live-migrn-rfcv1
git cherry-pick FETCH_HEAD
```

---

## 2. 需要哪些 patch(完整清单)

### 2.1 QEMU 侧(8 个,全部在 `patches/qemu/`)

| # | Patch | 作用 |
|---|---|---|
| 1 | `hw/arm/smmuv3-accel: Factor out the single vEVENT read` | 纯重构,为 drain 做准备 |
| 2 | `hw/arm/smmuv3-accel: Drain the vEVENTQ when the VM stops` | 停机时排空内核 vEVENTQ 到 guest 事件队列,事件不丢 |
| 3 | `hw/arm/smmuv3: Migrate the accelerator feature set` | 迁移 IDR0~5,两端不一致 load 失败 |
| 4 | `hw/arm/smmuv3-accel: Add a helper to replay all STEs` | 目的端重走 guest 流表重建 vDEVICE/nested HWPT |
| 5 | `hw/arm/smmuv3-accel: Restore accelerator state on incoming migration` | post_load:恢复 vEVENTQ/GBPA HWPT/重放 STE |
| 6 | `hw/arm/smmuv3-accel: Request dirty tracking on the nesting parent` | 让 VFIO 在 S2 nesting parent 上开脏页跟踪 |
| 7 | `hw/arm/smmuv3: Support migration with accel=on` | 拆 accel 全局迁移 blocker(仅留 CMDQV 的) |
| 8 | `pci/pcie: Do not check Link Status 2 across a migration` | **邮件系列外的作者分支提交**,root-port 场景必需 |

### 2.2 QEMU 基线里已含的前置(无需单独获取)

基线 `99e54ab5e7`(2026-09-03 upstream master)已合入:
- *user-creatable accelerated SMMUv3* 主系列 v9(37 patch,`smmuv3-accel.c/h/stubs`、
  `-device arm-smmuv3,accel=on` 属性模型、vDEVICE、GBPA HWPT)
- *vEVENTQ support* v3(4 patch,`IOMMUFDVeventq` 后端)
- *Tegra241 CMDQV* 系列

### 2.3 内核侧(**不需要自己打 patch**)

直接用作者分支,所需组件全齐:

| 组件 | 在哪 | 说明 |
|---|---|---|
| iommupt 页表栈 | Jason Gunthorpe 的开发分支(含在作者分支内) | 大重构,未进主线 |
| **s2-DBM 脏页跟踪** | 栈顶 `iommu/arm-smmu-v3: Enable stage-2 dirty tracking for nested domains`(仅 18 行,`patches/kernel/` 有导出) | 允许 `DIRTY_TRACKING+NEST_PARENT` 组合;无 DBM 硬件时返回 `-EOPNOTSUPP`;**作者注明 Not tested** |
| vEVENTQ UAPI | 分支内 `IOMMUFD_CMD_VEVENTQ_ALLOC` 等 | QEMU vEVENTQ 后端依赖 |
| vIOMMU ARM_SMMUV3 | 分支内 | vDEVICE/嵌套 STE 依赖 |
| **hisi_acc 迁移驱动** | 分支内 `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | 与 openEuler 6.6 版本仅 232 行纯重构差异,**无功能差异**(已人工核对) |

### 2.4 内核要不要改?——明确结论

- **代码:不用改。** 作者分支包含全部依赖(含海思驱动);`hisi_acc_vfio_pci.c` 与
  openEuler 6.6 版本 diff 232 行均为重构(`hisi_qm_mb_read` 抽取、命名、花括号风格)
- **要做的只有:**
  1. config(见 §3.2)
  2. **验证平台启动**:该分支是 mainline 基础,若测试服务器依赖 openEuler 6.6 的
     平台私货(dtb/驱动/早期初始化),需把相应补丁移植过来 —— 这是唯一的潜在内核工作量
- **不要走的路:** 在 openEuler 6.6 上补新特性 —— 6.6 的 iommufd 是旧一代
  (无 vEVENTQ、无新 vIOMMU 语义、无 iommupt),QEMU 新 accel 栈完全对不上,等于重写

---

## 3. 环境要求

### 3.1 硬件

- 两台 aarch64 宿主机(源/目的)。**强烈建议同型号**——patch 3 会校验两端解析出的
  IDR(ril/ats/oas/ssidsize)一致,不同型号宿主机的 SMMUv3 特性差异会直接导致 load 失败;
  且 hisi_acc 迁移有 match 机制(vf_qm_check_match),**两端必须是同型号加速器**
- 每台一块 VFIO 可迁移设备:海思加速器 VF(zip / sec / hpre 均可)
  - 迁移驱动:`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c`,支持 `STOP_COPY | PRE_COPY`
  - **QM 硬件代次要求:迁移区域仅 `qm->ver > QM_HW_V3`(即 V4=0x50 / V5=0x51)**,
    老平台(Kunpeng920 为 V2)没有 migration region,先确认卡的新旧
- 宿主机 SMMUv3 需支持(QEMU 启动时会逐项检查,不满足即报错退出):
  - 嵌套翻译(vIOMMU type `ARM_SMMUV3`)
  - 流表格式匹配、STE 小端、AArch64 翻译、RIL(range invalidation)
  - SIDSIZE/SSIDSIZE 兼容、IPA 位数、guest 所用页粒度(4K/16K/64K)
  - **HTTU/DBM(S2 脏页跟踪的硬门槛)**:IDR0.HTTU ≥ HA+HD;ACPI 下 IORT 固件覆盖值也算数
    (arm_smmu_get_httu() 的逻辑)。**没有 DBM:内核对 nesting parent 的
    DIRTY_TRACKING 请求返回 `-EOPNOTSUPP`,patch 6 路径完全测不了**

#### Pre-flight 检查清单(跑测试前逐项确认)

| # | 检查项 | 命令/方法 | 期望 |
|---|---|---|---|
| 1 | 作者内核能启动 | 装上 `iommu_pt_arm64_s2_dbm` 内核重启 | 正常起机、SMMU/iommufd/加速器驱动均探测 |
| 2 | 宿主机 SMMU HTTU/DBM | `dmesg \| grep -i smmu`(看 HTTU override 警告) | IDR0.HTTU ≥ HA+HD |
| 3 | 加速器 QM 代次 | `lspci -nn -d 19e5:` + 平台代次;或绑 hisi_acc 后看 migration state | V4/V5(migration region 存在) |
| 4 | VFIO 迁移支持 | `ls /sys/bus/pci/devices/<VF_BDF>/vfio-dev/vfio*/migration/` | 存在 |
| 5 | 两端同型号加速器 + 同内核 commit | — | 一致 |
| 6 | guest 驱动非 SVA 模式 | guest `dmesg \| grep -i uacce` | 无 SVA(本 RFC 无 IOPF) |

### 3.2 宿主机内核

```bash
git clone -b iommu_pt_arm64_s2_dbm https://github.com/shamiali2008/linux.git
```

- 栈顶关键提交:`iommu/arm-smmu-v3: Enable stage-2 dirty tracking for nested domains`
  (18 行;`patches/kernel/` 有导出;**作者注明 "Not tested"**)
- config 必开:`CONFIG_IOMMUFD=y CONFIG_IOMMUFD_VFIO=y CONFIG_VFIO=y CONFIG_VFIO_PCI=y
  CONFIG_ARM_SMMU_V3=y CONFIG_KVM=y CONFIG_CRYPTO_DEV_HISI_*=(zip/sec/hpre 按测试卡勾)`
- **两端用同一内核 commit**
- QEMU 树内 `linux-headers/` 已含 vEVENTQ UAPI,构建 QEMU 不依赖宿主机内核头

### 3.3 QEMU 构建(两端同一份二进制)

```bash
cd /home/akira/code/qemu/qemu
git checkout smmuv3-accel-live-migrn-rfcv1
mkdir build && cd build
../configure --target-list=aarch64-softmmu
ninja -j$(nproc)
```

### 3.4 Guest

- **现有 openEuler guest 镜像即可**:guest 侧只需 `arm-smmu-v3` 驱动 + 海思加速器 guest 驱动,
  **不需要任何新内核特性**(vEVENTQ/脏页跟踪全是宿主机侧机制)
- accel 模式**仅支持 ACPI 启动**(virt 机默认 ACPI,勿加 `acpi=off`/dtb 启动)
- 负载必须**非 SVA 模式**(本 RFC 是无 IOPF 的 vSMMU 热迁移;guest 的 vSMMU 不暴露 SVA 能力,
  uacce 设备不会带 SVA 标志,libwd/驱动自动走 map/unmap 模式):
  - **zip**:uacce + libwd(`wd_util`/hzip 工具,持续压缩吞吐)
  - **sec/hpre**:AF_ALG 内核 crypto(openssl speed 等),或 uacce + libwd
  - 跑迁移前先在 guest 里确认负载正常、`dmesg` 无 SMMU 故障

---

## 4. 拓扑与命令行

### 4.1 硬约束(违反直接报错)

1. **accel SMMU 的总线上只允许 vfio-pci(+iommufd)端点**。仿真设备(disk/net 走 PCI)会被拒:
   `Emulated endpoint devices are not allowed when using arm-smmuv3,accel=on`
   → 磁盘/网络用 **virtio-mmio**(`virtio-blk-device`/`virtio-net-device`),或放第二个 root bus
2. **必须 KVM + kernel-irqchip**(virt 机默认满足):`SMMUv3 accel=on requires KVM with kernel-irqchip=on`
3. 不能与整机选项 `-machine virt,iommu=smmuv3` 同用
4. `msi-gpa`、`pci_preserve_config`、IORT RMR(MSI 1:1 窗口 0x8000000+1M)**全部自动处理**,无需手填
5. 两端 QEMU 命令行除 `vfio-pci,host=` 的 BDF 和 `-incoming` 外**必须一致**(RAM/CPU/拓扑)

### 4.2 源端命令行模板

```bash
qemu-system-aarch64 \
  -machine virt -accel kvm -cpu host -smp 8 -m 32G \
  -device arm-smmuv3,primary-bus=pcie.0,id=smmuv3.0,accel=on \
  -object iommufd,id=iommufd0 \
  -device pcie-root-port,id=rp0,bus=pcie.0 \
  -device vfio-pci,host=0000:xx:00.0,iommufd=iommufd0,bus=rp0 \
  -drive file=guest-image.qcow2,if=none,id=drv0 \
  -device virtio-blk-device,drive=drv0 \
  -netdev user,id=net0 \
  -device virtio-net-device,netdev=net0 \
  -nographic -monitor unix:/tmp/mon-src,server,nowait
```

说明:
- 设备建议挂在 `pcie-root-port` 下(常见做法;作者的第 8 个提交就是修 root-port 场景)
- 若 guest 直启内核:`-kernel Image -append "root=... console=ttyAMA0"`(注意仍走 ACPI,勿传 dtb)
- 加 trace:`-trace enable=smmuv3_accel_*` 观测 STE 安装/翻译

### 4.3 目的端命令行模板

同上,改两处:

```bash
  -device vfio-pci,host=0000:yy:00.0,iommufd=iommufd0,bus=rp0 \   # 目的机上的 BDF
  ...
  -incoming tcp:0:4444 \
  -nographic -monitor unix:/tmp/mon-dst,server,nowait
```

(也可 `-incoming defer` 后在 monitor 里 `migrate_incoming tcp:0:4444`)

### 4.4 迁移操作

```bash
# 源端 monitor
(qemu) migrate_set_capability events on        # 可选,便于统计
(qemu) migrate -d tcp:<dest_ip>:4444
(qemu) info migrate                            # 关注 remaining / total time / downtime
(qemu) info status                             # 迁移完成后应为 running (finish phase)
```

---

## 5. 测试用例

### TC1 冒烟:accel=on + vfio 基本功能(不迁移)
1. 启动 VM,guest 内确认:`dmesg | grep -i smmu`(arm-smmu-v3 探测成功、无 event 风暴)
2. 加速器驱动加载、下发任务成功
3. 源端 QEMU 加 `-trace enable=smmuv3_accel_*`:应看到 `smmuv3_accel_install_ste`(vSID → hwpt)
**通过标准**:设备功能正常,无 SMMU 故障

### TC2 空载迁移
1. 设备空闲(驱动已加载,无任务),执行迁移
2. 迁移完成后目的端:guest 继续运行,`info migrate` 显示 completed,设备可下发新任务
**失败观察点**:目的端报 `Failed to restore the vEVENTQ/GBPA HWPT/replay the stream table`
(post_load,patch 5)或 IDR mismatch(patch 3)

### TC3 负载下迁移(核心用例,覆盖 patch 4/5)
1. guest 内跑加速器持续压测:**zip 持续压缩流 / sec-hpre 持续加解密**(长流 DMA 任务,跨整个迁移窗口)
2. 迁移期间**不停任务**;迁移完成后任务继续、结果校验通过、guest 无 SMMU fault
3. 迁移后继续跑新任务 ≥10 分钟(证明重放后的映射持续可用,非一次性)
**通过标准**:任务零失败或与不迁移的基线一致

### TC4 脏页跟踪数据完整性(patch 6 专项,海思设备最关键用例)
1. guest 内让加速器向一段大 buffer 持续写结果(输出型任务),内容可校验(CRC/序号,如解压校验)
2. 迁移(cutover 前设备一直在写)
3. 迁移后校验 buffer 内容完整
**说明**:`hisi_acc_vfio_pci` **没有设备自跟踪脏页**(dirty_bytes 恒 0,无 dirty bitmap ops),
迁移期间设备写的每一页 guest 内存**完全依赖 patch 6 使能的 S2 nesting parent 脏页跟踪**——
这正是 RFC cover letter 点名的场景("assigned devices that cannot track dirty pages themselves"),
也是海思加速器作为测试对象的最大价值。失败表现:迁移后输出 buffer 尾部数据丢失/陈旧

### TC5 vEVENTQ 排空(patch 1/2)
1. guest 内制造 pending 翻译事件:向未映射 IOVA 发起 DMA(用 wd/libwd 向坏地址发任务;
   或先映射 → DMA 进行中 unmap)
2. 立即发起迁移,观察源端 stop 阶段
3. 迁移后 guest `dmesg` 应有对应 arm-smmu-v3 event 记录(事件未丢)
4. 源端可加 `-trace enable=smmuv3_*` 观察停机时的事件写入
**说明**:若设备侧难以精确制造故障,至少验证"迁移不丢正常事件、不引入事件风暴"回归

### TC6 IDR 不匹配负向测试(patch 3)
1. 源端 `-device arm-smmuv3,...,accel=on,ril=off`,目的端用默认(`ril=auto`→按宿主机解析为 on)
2. 发起迁移
**期望**:目的端 load 失败,报错:
```
SMMUv3 IDR3 mismatch: source 0x..., destination 0x...
ril, ats, oas and ssidsize must resolve to the same values on source and destination.
```
3. 反向验证:两端参数完全一致(同型宿主机)→ TC2/TC3 通过即覆盖

### TC7 迁移 blocker(patch 7)
1. accel=on、无 CMDQV:迁移可正常发起(本 RFC 的目标行为)
2. (可选对照)切回基线 `99e54ab5e7` 构建同命令行 VM:应被
   `Migration not supported with SMMUv3 accelerator mode enabled` 阻塞 → 证明 blocker 确实被移除
3. CMDQV:海思平台无 Tegra241 CMDQV,标记 N/A

### TC8 稳定性
1. 源⇄目的来回迁移 ≥5 次(ping-pong)
2. 迁移中 `migrate_cancel` 后重新迁移
3. 迁移后 guest 内做新的 map/unmap(新任务、新 buffer)继续正常

---

## 6. 结果记录表

| 用例 | 日期 | 源机型号/BDF | 目的机型号/BDF | 内核 commit | QEMU commit | 结果 | 备注/日志 |
|---|---|---|---|---|---|---|---|
| TC1 | | | | | | | |
| TC2 | | | | | | | |
| ... | | | | | | | |

关键日志留存:
- 两端 QEMU 完整命令行、`info migrate` 输出
- guest `dmesg`(迁移前后)、宿主机 `dmesg | grep -iE "smmu|iommufd|vfio"`
- 失败时的 QEMU 报错全文(post_load 错误最有价值)

---

## 7. 回复 Tested-by

通过后回复邮件列表(纯文本):

- 回复对象:逐封回复 7 个 patch 邮件(最稳妥),或在 cover letter 回复中说明适用于全部
- 收件人:qemu-devel@nongnu.org,CC 作者 skolothumtho@nvidia.com、eric.auger@redhat.com
- 格式示例(回复 patch 7/7):

```
On 9/4/26 7:05PM, Shameer Kolothum wrote:
> hw/arm/smmuv3: Support migration with accel=on
> ...

Tested on <板卡型号>(2x <海思加速器型号>,VFIO migration capable), host kernel
<内核 commit / iommu_pt_arm64_s2_dbm>, QEMU smmuv3-accel-live-migrn-rfcv1
(99e54ab5e7 + this series + pci/pcie Link Status 2 fix from your branch).

- accel=on + vfio-pci passthrough boot & DMA: OK
- live migration under sustained accelerator workload: OK, N iterations
- dirty tracking data integrity across cutover: OK
- IDR mismatch (ril=off vs auto) correctly fails load: OK

Tested-by: Your Name <your.email@example.com>
```

注意事项:
- **只有真正执行过的 patch 才加 Tested-by**;patch 1 是纯重构,通常随系列整体 Tested-by
- 发现问题:回复描述复现步骤,**不加 Tested-by**(或仅在确认不受影响的 patch 上加)
- RFC 阶段的失败反馈同样有价值(作者原话:他没有真机可测,欢迎早期反馈)
- 用 `b4 reply <msgid>` 可自动处理 in-reply-to

---

## 8. 已知风险与提醒

1. **全栈首次真机验证**:作者 QEMU RFC 未做过真机迁移测试(cover letter 原话),内核 s2-dbm
   提交也注明 "Not tested",且整个 iommupt 页表栈是开发中的大重构——**踩坑是预期内的,坑本身就是反馈**。
   定位问题时先区分:内核 iommupt 栈问题 / s2-dbm 问题 / QEMU RFC 问题 / hisi_acc 驱动问题
2. **宿主机 SMMU 必须有 HTTU/DBM**:没有 DBM,内核对 nesting parent 的脏页跟踪请求
   返回 `-EOPNOTSUPP`,patch 6 路径无法启用(设备 attach 即失败)
3. **QM 硬件代次**:migration region 需要 QM V4/V5;Kunpeng920(V2)不行
4. **作者内核分支的平台启动**:mainline 基础,若测试服务器依赖 openEuler 6.6 私货补丁需先移植
5. guest 加速器负载必须非 SVA(无 PRI/IOPF)
6. 两端不同 CPU 型号时 `-cpu host` 会导致迁移失败(CPU 特性不匹配),与 SMMU 无关,
   同型宿主机或统一 `-cpu cortex-a76` 等命名模型可规避
7. 设备 BDF 两端不同没关系(`vfio-pci,host=` 各自指定);hisi_acc 的 match 机制要求两端同型号加速器
8. 本分支含作者第 8 个 pci 提交;若最终报告问题,注意区分它是否参与

---

## 9. 附:海思加速器适配可行性结论(代码证据)

| 证据 | 结论 |
|---|---|
| `hisi_acc_vfio_pci.c` 在 openEuler 6.6(1797 行)与作者内核分支(1741 行)均存在,diff 232 行**纯重构**(hisi_qm_mb_read 抽取、变量命名、花括号风格) | 驱动可用,无需移植 |
| 该驱动 `migration_flags = STOP_COPY \| PRE_COPY`,`mig_ops` 完整;但 **`dirty_bytes=0`、无 dirty bitmap 实现** | 设备不自跟踪脏页 → **完全落在 patch 6 的场景** |
| 迁移状态 = QM 硬件态(PF migration region),`qm.c` 中 `ver > QM_HW_V3` 才使能 | 需 QM V4/V5 平台 |
| 作者内核分支 UAPI:`IOMMUFD_CMD_VEVENTQ_ALLOC`/`IOMMU_VIOMMU_TYPE_ARM_SMMUV3` 均在;`arm_smmu_get_httu()` 要求 IDR0.HTTU≥HA+HD(ACPI 下 IORT 覆盖值也算) | 内核依赖齐;硬件门槛明确 |
| patch 6 链路:QEMU `VIOMMU_FLAG_WANT_NESTING_DIRTY_TRACKING`(QEMU 内部抽象,`include/hw/core/iommu.h`)→ `hw/vfio/iommufd.c:446` 在 nesting parent HWPT 上加 `IOMMU_HWPT_ALLOC_DIRTY_TRACKING`(前提:内核报 `IOMMU_HW_CAP_DIRTY_TRACKING`)→ 内核置 `PT_FEAT_ARMV8_DBM` + STE.S2HA/S2HD | 链路完整,可测 |

**结论:能测,且海思加速器(无自跟踪脏页的可迁移 VFIO 设备)正是该 RFC 最想收到的测试对象。**
