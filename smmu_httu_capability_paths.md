# SMMUv3 HTTU 能力位与 HA/HD 赋值链完整分析

> 分析对象:
> - openEuler QEMU(`/home/akira/code/openeuler_qemu/qemu`,`hw/arm/smmuv3.c`)
> - openEuler 内核 6.6(`/home/akira/code/openeuler/kernel`,guest 侧 arm-smmu-v3 驱动)
> 规格依据:ARM IHI 0070 H.a(SMMUv3 Architecture Specification)§6.3.1, p.369
>
> 所有行号均已在对应源码树中逐一核实。

---

## 0. 结论速览

| 问题 | 答案 |
|---|---|
| QEMU 会不会修改 SMMU HTTU 能力位? | guest 看到的 `SMMU_IDR0.HTTU` 恒为 0b00:仿真路径"从不写",嵌套路径"白名单不透传"。启动后 IDR 只读,永不再变 |
| KVM 模式下也是 0 吗? | 是。KVM 没有 in-kernel SMMU 仿真,vSMMU 的 MMIO 在 TCG/KVM 下都由 QEMU 用户态同一份代码处理 |
| guest 填的 CD.HA/HD 是多少? | **恒 0**。唯一赋值语句(内核 `arm_smmu_make_s1_cd`)的上游条件恒假 |
| guest/host 填的 STE.S2HA/S2HD 是多少? | **恒 0**。openEuler 6.6 内核没有写这两个字段的任何代码 |
| STE 看 KVM 的能力吗? | 不看。KVM 的能力位(VTCR_EL2.HA/HD/HDBSS)作用于 **CPU 页表**,与 SMMU STE/CD 是平行机制 |
| "SMMU 直通"(nested/accel)下会变吗? | 不会。直通的是**翻译动作**,不是**能力声明**;guest 决策依据仍是 vSMMU 的 IDR(HTTU=0) |

---

## 1. HTTU 能力位定义(spec)

### 1.1 寄存器位:SMMU_IDR0.HTTU, bits [7:6]

| HTTU[7:6] | 含义 |
|---|---|
| 0b00 | 不支持硬件标志更新 |
| 0b01 | 仅支持 Access flag (AF) 硬件更新 |
| 0b10 | 支持 Access flag **+ Dirty state (DBM)** 硬件更新 |
| 0b11 | 同 0b10,且支持表描述符的 AF 更新 |

注意:HTTU **只存在于 IDR0**,IDR3 中没有对应字段(IDR3 的 bit[7]=MPAM、bit[6]=RES0)。
字段位置是**架构固定定义**的;只有取值是 IMPLEMENTATION DEFINED。

三方交叉验证一致:ARM spec(IHI 0070 H.a p.369)、QEMU(`FIELD(IDR0, HTTU, 6, 2)`)、
Linux 内核(`IDR0_HTTU GENMASK(7, 6)`,`IDR0_HTTU_ACCESS=1`,`IDR0_HTTU_ACCESS_DIRTY=2`)。

### 1.2 容易混淆的 IDR3.HAD(bit 2)

`SMMU_IDR3.HAD` 是 **Hierarchical Attributes Disable**(CD.HAD0/1 支持),
与 HTTU 的 Access flag / Dirty state 更新**语义无关**,见 commit `e7c3b9d9a0`。

### 1.3 配套的软件接口位

| 位置 | 位 | 作用 |
|---|---|---|
| CD.TCR | HA(bit 43)/ HD(bit 42) | 软件在 Context Descriptor 中请求 stage-1 硬件 AF/Dirty 更新 |
| STE | S2HA(bit 184)/ S2HD(bit 183) | 软件在 Stream Table Entry 中请求 stage-2 硬件 AF/Dirty 更新 |
| ACPI IORT SMMUv3 节点 Flags | bits [2:1] | HTTU override(`ACPI_IORT_SMMU_V3_HTTU_OVERRIDE`) |
| LPAE 页表 PTE | DBM(bit 51) | 硬件脏位标记,依赖 HTTU 支持 |

---

## 2. QEMU 中 IDR 的写入机制

### 2.1 寄存器操作的三个宏(`include/hw/registerfields.h`)

| 宏 | 定义位置 | 角色 | 碰不碰寄存器值 |
|---|---|---|---|
| `FIELD(reg, field, shift, length)` | :42-46 | **声明位图**:生成 `R_*_SHIFT/LENGTH/MASK` 编译期常量 | ❌ 纯编译期,不读不写 |
| `FIELD_EX32(storage, reg, field)` | :55-57 | **读**:extract 出字段 | 读 |
| `FIELD_DP32(storage, reg, field, val)` | :101-108 | **写**:deposit32 读-改-写 | 写 |

`FIELD(IDR0, HTTU, 6, 2)`(`smmuv3-internal.h:42`)只是登记"HTTU 住在 IDR0 bit[7:6]",
本身不执行任何赋值——类似定义结构体成员偏移量。

### 2.2 `s->idr[0]` 的值来源:三层结构

`s->idr[0]` 是 `SMMUv3State` 结构体里的普通内存字段(`include/hw/arm/smmuv3.h:42`,
`uint32_t idr[6]`),不是 MMIO,不指向硬件。值由三层构成:

1. **初始值 = 0**:QEMU 创建设备对象时 `g_malloc0` 清零整个状态(**不是从硬件读的**);
2. **仿真常量 deposit**:`smmuv3_init_regs()` 每条 `FIELD_DP32` 的第 4 个参数是编译期常量
   (字面量在 `smmuv3.c:340-373`,少数值宏在 `smmuv3-internal.h:76-79、108`),
   语义是"QEMU 仿真模型声明自己支持什么",与宿主机硬件无关;
3. **嵌套白名单覆盖**:`smmuv3_nested_init_regs()` 经 iommufd 读宿主机真实 IDR 后,
   把白名单字段的**运行时值** deposit 进来(`smmuv3.c:300-331`)。

默认仿真模式下 IDR0 的最终值(逐位分解):

```
bit 0     S1P=1        ┐
bit 3:2   TTF=2 (0b10) │
bit 4     COHACC=1     │ 一堆非零位
bit 12    ASID16=1     │
bit 18    VMID16=1     │
bit 22:21 TTENDIAN=2   │
bit 26    TERM_MODEL=1 │
bit 28:27 STLEVEL=1    ┘
bit 7:6   HTTU=00      ← 唯独这里是 0

IDR0 = 0x0C441019(0x19 = 0b0001_1001,bit[7:6]=00)
```

### 2.3 全仓库 `s->idr[]` 的全部写入点(穷尽验证)

```
┌─ smmuv3_init_regs()            smmuv3.c:336   仿真默认值(所有模式都跑)
└─ smmuv3_nested_init_regs()     smmuv3.c:261   嵌套模式下用宿主机值覆盖白名单字段
```

设备属性只有 `stage`(smmuv3.c:2363),**没有任何可配置 IDR 的用户接口**;
IDR0~IDR5 为只读寄存器(guest 写入被忽略,读路径 `smmuv3.c:2073-2075` 原样返回);
`vmstate_smmuv3`(smmuv3.c:2320-2349)**不含 idr[]**,热迁移时目的端 reset 重新构造。

**HTTU 相关代码全仓库只有 2 处**:

```
hw/arm/smmuv3-internal.h:42:  FIELD(IDR0, HTTU, 6, 2)    ← 位图声明,从未被使用
hw/arm/smmuv3.c:785:          goto bad_cd; /* HTTU = 0 */ ← 注释
```

没有任何 `FIELD_DP32(..., IDR0, HTTU, ...)`(写)或 `FIELD_EX32(..., IDR0, HTTU)`(读)
的调用——**这 2 个 bit 从对象清零分配起,无任何代码路径碰过它**。

---

## 3. 非嵌套虚拟化路径(普通 `-M virt,iommu=smmuv3`,TCG/KVM)

### 3.1 调用链

```
-M virt,iommu=smmuv3
→ virt.c 创建 arm-smmuv3 设备
→ smmu_realize()                          smmuv3.c:2225
     └ 2233-2236:nested 未开启(非嵌套默认 false)
→ 设备 reset
→ smmu_reset_hold()                       smmuv3.c:2213
→ smmuv3_init_regs()                      smmuv3.c:336   ★ 唯一写入点
     ├ 340-354:IDR0 只写 9 个字段(S1P/S2P、TTF、COHACC、ASID16、
     │           VMID16、TTENDIAN、STALL_MODEL、TERM_MODEL、STLEVEL)
     │           ★ 没有任何一行写 IDR0.HTTU → 恒为 0b00
     ├ 361-367:IDR3(HAD=1、XNX、RIL=1、BBML=2;HAD 是分层属性,与 HTTU 无关)
     └ 376:调 smmuv3_nested_init_regs()
              → smmuv3.c:270 因 nested=false 直接 return,不做任何覆盖
```

### 3.2 KVM 模式为什么也一样:vSMMU 没有 in-kernel 仿真

KVM 没有 SMMUv3 的内核态设备模型(不像 GIC 有 `/dev/kvm` 设备),设备模型永远是
QEMU 用户态那一份代码:

| 模式 | guest 读 SMMU_IDR0 的路径 | 结果 |
|---|---|---|
| TCG | MMIO → QEMU `smmuv3_readl()` → `s->idr[0]` | bit[7:6]=0 |
| KVM(普通) | MMIO → **KVM exit 到用户态** → 同一个 `smmuv3_readl()` → 同一个 `s->idr[0]` | bit[7:6]=0 |

TCG/KVM 只改变 vCPU 怎么执行,不改变设备模型。

### 3.3 HTTU 值的生命周期

| 阶段 | HTTU 值 | 说明 |
|---|---|---|
| 启动构造(reset) | **0b00** | `smmuv3_init_regs()` 从不写该字段 |
| 运行时 | 0b00(不变) | IDR 只读;写路径无 case,写入被忽略 |
| guest 重启 / system_reset | 0b00(重建) | reset → `init_regs` 重跑,幂等 |
| 热迁移 | 0b00(重建) | vmstate 不含 idr[],目的端 reset 重新构造 |

**结论:非嵌套下 HTTU 不存在"被修改"——它是一个从未被写过的常量 0b00。**
guest 面对的是 QEMU 纯软件仿真 SMMU,宿主机 SMMU 硬件的能力在该路径**零参与**
(不存在"读进来再改掉",而是根本没有输入)。

---

## 4. 嵌套虚拟化 / "SMMU 直通"路径(arm-smmuv3-accel + iommufd viommu)

### 4.1 启用条件

- 设备类型为 `arm-smmuv3-accel`,`smmu_accel_realize()`(`smmuv3.c:2270`)在 2279 行
  显式设置 `nested=true`;
- `stage` 必须为 "1"(`smmuv3.c:2233-2236`:stage≠"1" 时 nested 被强制置 false);
- 存在 iommufd viommu(`bs->viommu != NULL`)。

### 4.2 调用链与白名单

```
smmu_accel_realize()                      smmuv3.c:2270(nested=true)
→ 设备 reset
→ smmu_reset_hold()                       smmuv3.c:2213
→ smmuv3_init_regs()                      smmuv3.c:336
     ├ 先构造仿真默认值(同第 3 节,HTTU 仍为 0)
     └ 376:smmuv3_nested_init_regs()     smmuv3.c:261
          ├ 270:if (!bs->nested || !bs->viommu) return;   ← 非嵌套在此退出
          ├ 274:device_list 为空 → return
          ├ 279:二次 reset 复用缓存 hw_info("reusing the previous hw_info")
          ├ 284:smmu_dev_get_info()       ← 读宿主机真实 IDR
          │      → smmu-common.c:836
          │      → iommufd_backend_get_device_info()
          │      → IOMMUFD IOMMU_GET_HW_INFO ioctl(IOMMU_HW_INFO_TYPE_ARM_SMMUV3)
          │      失败则 error_report + return(不做任何覆盖)
          └ 300-331:★ 白名单逐字段覆盖 guest 可见的 s->idr[]
```

白名单(nested 模式下从宿主机透传的字段):

| 目标寄存器 | 透传字段 | 代码位置 |
|---|---|---|
| IDR0 | BTM、ATS、ASID16、TERM_MODEL、STALL_MODEL、STLEVEL | smmuv3.c:300-311 |
| IDR1 | SIDSIZE、SSIDSIZE(取自 pasid) | smmuv3.c:313-315 |
| IDR3 | HAD、RIL、BBML | smmuv3.c:317-322 |
| IDR5 | GRAN4K、GRAN16K、GRAN64K、OAS | smmuv3.c:324-331 |

**★ IDR0.HTTU 不在白名单中** —— 即使宿主机 SMMU 的 IDR0.HTTU=0b10,
该值也会被丢弃,guest 看到的仍是仿真默认的 0b00。
这是整个代码库中唯一存在"宿主机 HTTU 值被读入后被修改(丢弃/mask 为 0)"的位置。
内核侧与此一致:`include/uapi/linux/iommufd.h` 明确注释嵌套虚拟化
当前不支持 HTTU、BTM、MPAM 等特性。

### 4.3 "直通"模式的转发细节(`smmuv3_install_nested_ste`,smmuv3.c:1424-1489)

**直通的是翻译动作,不是能力声明。** 转发给宿主机的 guest STE 内容:

```c
nested_data.ste[0] = ste.word[0] | ste.word[1] << 32;  /* V|CONFIG|S1FMT|S1CTXPTR|S1CDMAX */
nested_data.ste[1] = ste.word[2] | ste.word[3] << 32;  /* S1DSS|S1CIR|S1COR|S1CSH|S1STALLD|EATS */
nested_data.ste[0] &= 0xf80fffffffffffffULL;           /* 掩码白名单 */
nested_data.ste[1] &= 0x380000ffULL;
```

- 只转发 **STE word0-3(前 128 位,S1 相关字段)** 并做位掩码过滤;
  **S2HA(bit184)/S2HD(bit183)所在的 word5 根本不在转发范围内**——
  即使 guest 置了,也到不了宿主机;
- 该路径**不跑 `decode_cd`**(只取 STE,CD 由宿主机硬件从 guest 内存直接读),
  C_BAD_CD 防线在此模式不在路径上——但无关紧要,因为 guest 的决策源头
  (vSMMU IDR0.HTTU=0)已经把一切关死了。

**判断 guest 填什么,只看 guest 的"世界观"——vSMMU 报告的 IDR0.HTTU。**
"直通"改变的是翻译由谁执行(软件仿真 → 宿主机硬件),从不改变能力发现。

---

## 5. ACPI IORT 路径(两种模式共用,不改变 HTTU)

`hw/arm/virt-acpi-build.c:811` 构造 IORT SMMUv3 节点:

```c
build_append_int_noprefix(table_data, 1 /* COHACC Override */, 4); /* Flags */
```

Flags 只置 bit0(COHACC Override),bits[2:1](HTTU override)为 0,
即**不做 HTTU 覆盖**,guest 完全依赖 SMMU_IDR0.HTTU 寄存器探测(结果仍为 0)。
这也是唯一的"强制旁路"入口:若固件强行设置 IORT HTTU_OVERRIDE,内核会
无视寄存器值置 FEAT_HD、填 HA/HD=1 的 CD,然后被 QEMU `decode_cd` 报
C_BAD_CD,设备 DMA 直接出错——强开不解决问题。

---

## 6. `decode_cd` 的运行时拒绝:`/* HTTU = 0 */` 注释语义

```c
/* smmuv3.c:773-786 decode_cd() —— 校验 guest 提交的 Context Descriptor */
if (!CD_VALID(cd) || !CD_AARCH64(cd)) {
    goto bad_cd;
}
if (!CD_A(cd)) {
    goto bad_cd; /* SMMU_IDR0.TERM_MODEL == 1 */   ← 同款注释句式
}
if (CD_HA(cd) || CD_HD(cd)) {
    goto bad_cd; /* HTTU = 0 */                     ← 拒绝理由,不是修改动作
}
...
bad_cd:                                            /* smmuv3.c:834-836 */
    event->type = SMMU_EVT_C_BAD_CD;
    return ret;
```

- 注释含义:**"因为本 SMMU 的 HTTU 能力是 0,所以带 HA/HD 的 CD 是非法的,必须拒绝"**。
  它描述设备能力的既有状态(那个恒为 0b00 的常量),这一行没有改任何值;
  被"读"的是 guest 的 CD 字段(`CD_HA/CD_HD`,smmuv3-internal.h:642-643)。
- spec 规则:SMMU 不支持相应 HTTU 能力时,CD.TCR 的 HA/HD 是 **RES0**;
  软件往 RES0 位写 1 → CD 非法 → SMMU 必须上报 C_BAD_CD 事件。

| | 位置 | 角色 |
|---|---|---|
| `IDR0.HTTU = 0`(从不写) | `smmuv3_init_regs()` | **告示牌**:告诉守规矩的 guest 驱动"我不支持 HTTU,别用" |
| `if (CD_HA \|\| CD_HD) goto bad_cd` | `decode_cd()`,smmuv3.c:784 | **护栏**:拦住无视能力位、强行置 HA/HD 的 guest,报 C_BAD_CD |

两者必须配套:只改 IDR0.HTTU 宣传能力而不放开此检查,guest 一用 HA/HD
就收到 C_BAD_CD;宣传了却用不了。

---

## 7. guest 内核侧:CD.HA/HD 的完整赋值链(openEuler 6.6 源码验证)

### 7.1 五级门控链

```
[第0级·源头] vSMMU 的 SMMU_IDR0.HTTU = 0b00
             (QEMU 仿真从不写;嵌套白名单 smmuv3.c:300-311 也不透传)
      ↓ guest 内核读寄存器
[第1级·能力探测] arm-smmu-v3 驱动 probe:
    FIELD_GET(IDR0_HTTU, reg) → 0b00 → 不置 FEAT_HA / FEAT_HD
    (arm-smmu-v3.c:5550-5562,含 ACPI IORT HTTU_OVERRIDE 旁路;
     QEMU 生成的 IORT 未设,旁路不生效)
      ↓
[第2级·请求入口被堵] guest 用户态经 iommufd 请求脏跟踪:
    iommufd/hw_pagetable.c:126-127:
      if (flags & IOMMU_HWPT_ALLOC_DIRTY_TRACKING &&
          !device_iommu_capable(dev, IOMMU_CAP_DIRTY_TRACKING))   ← 恒 false
          return -EOPNOTSUPP;                                     ← 请求死在这
    (该 capability → arm_smmu_dbm_capable(),arm-smmu-v3.c:2562-2566,
     要求 FEAT_HD ∧ FEAT_COHERENCY)
      ↓
[第3级·quirk 判定] arm_smmu_domain_finalise(arm-smmu-v3.c:2715):
    置 IO_PGTABLE_QUIRK_ARM_HD 的两个入口都不通:
      a) S1 + enable_dirty(2755-2756)——第2级已把请求拒绝
      b) smmu->features & FEAT_HD(2783-2784,无条件)——FEAT_HD 恒假
      (S2 分支:enable_dirty 直接 return -EOPNOTSUPP,2762-2763)
      ↓
[第4级·唯一赋值语句] arm_smmu_make_s1_cd(arm-smmu-v3.c:1611-1614):
    memset(target, 0, ...) 起步;                 ← arm-smmu-v3.h:399-400 定义两个位
    if (pgtbl_cfg->quirks & IO_PGTABLE_QUIRK_ARM_HD)      ← 恒假
        target->data[0] |= CTXDESC_CD_0_TCR_HA (1UL<<43) |
                           CTXDESC_CD_0_TCR_HD (1UL<<42); ← 成对置 1
      ↓
[结果] guest 所有设备、所有 domain 的 CD:HA = HD = 0
(兜底:即便有 CD 带 HA/HD,QEMU decode_cd smmuv3.c:784 也会报 C_BAD_CD)
```

配套:quirk 成立时 io-pgtable 还会给 writable PTE 置 DBM 位
(`io-pgtable-arm.c:485-486`,`ARM_LPAE_PTE_DBM = 1<<51`)。

### 7.2 真实硬件对比(重要修正)

若 SMMU 报 HTTU=0b10(裸机真实硬件),第 3 级 b) 的**无条件**路径生效:

> **这套 6.6 内核会给所有 S1 domain 的 CD 都置 HA/HD=1**——
> 不只是请求了脏页跟踪的 domain(arm-smmu-v3.c:2783-2784)。

即 HA/HD 的取值规则在 6.6 内核里是:
`quirk = (S1 ∧ enable_dirty ∨ enable_dirty 被能力检查放行) ∨ FEAT_HD`
→ 真实硬件上全 1,vSMMU 下全 0。

### 7.3 "非零分支为什么存在"

内核是**运行时探测驱动的通用代码**:一份二进制要跑在裸机(真实 SMMU 报 0b10)、
KVM guest、QEMU、其他 hypervisor 上。寄存器值是运行时输入,分支必须覆盖所有
可能值。在这套 QEMU 里 0b01/0b10 分支是**永不执行的死分支**,但换个环境就活了。

---

## 8. STE.S2HA/S2HD:恒 0,且与 KVM 无关

### 8.1 三个事实(6.6 内核 + QEMU 双侧验证)

1. **内核 0 处引用**:`S2HA/S2HD` 在 drivers/iommu 和 include 下没有任何宏定义、
   赋值或读取。写 STE 的代码(arm_smmu_write_strtab_ent)从不碰这两个位。
   → 无论 guest 内核(guest 设备的 S1 STE)还是宿主机内核(VFIO 设备的 S2 STE),
   **S2HA/S2HD 恒 0**;
2. **S2 脏跟踪未实现**:`arm_smmu_domain_finalise()` 的 S2 分支直接
   `if (enable_dirty) return -EOPNOTSUPP;`(arm-smmu-v3.c:2762-2763);
3. **QEMU 侧对称**:`STE_S2HA/STE_S2HD` 宏已定义(smmuv3-internal.h:581-582),
   但全代码库**零处使用**——不校验、不透传、静默忽略。

### 8.2 澄清:"STE 看 KVM 的能力吗?"——不看,那是另一套机制

KVM 的能力位控制的是 **CPU stage-2** 的 `VTCR_EL2`,与 SMMU 的 STE/CD 平行:

| | SMMU 侧 | KVM/CPU 侧 |
|---|---|---|
| 控制寄存器 | STE.S2HA/S2HD、CD.TCR.HA/HD | `VTCR_EL2_HA(bit21)/HD(bit22)/HDBSS(bit45)`(arch/arm64/include/asm/kvm_arm.h:131-134) |
| 谁写 | arm-smmu-v3 驱动(本内核:不写) | KVM(`kvm_cap_arm_enable_hdbss()`,arch/arm64/kvm/arm.c:167) |
| 作用对象 | SMMU 设备 DMA 的表遍历 | vCPU 的 CPU 页表遍历 |
| 开启条件 | (未实现) | `system_supports_hdbss() ∧ VHE ∧ 未开 dirty ring ∧ size>0` → `vtcr |= VTCR_EL2_HD \| VTCR_EL2_HDBSS`(arm.c:200);关闭时清位(arm.c:152) |

KVM 不写任何 SMMU 的 STE/CD。即使 KVM 的 HDBSS 能力全开(CPU 侧硬件脏位跟踪
工作正常),SMMU 侧的 STE.S2HA/S2HD 依然是 0——两条通路完全独立。

---

## 9. 模式对比总表

| | 纯仿真(TCG) | KVM(普通) | nested/accel("SMMU 直通") | 裸机真实 SMMU(对比) |
|---|---|---|---|---|
| guest 读到的 HTTU | 0b00(QEMU 从不写) | 0b00(MMIO exit 到同一份用户态代码) | 0b00(宿主机值被白名单丢弃) | 0b10(真实硬件) |
| 有无"修改"动作 | 无(无输入,构造期即 0) | 无(同左) | 有(丢弃宿主机 HTTU 字段) | — |
| guest CD.HA/HD | **0** | **0** | **0**(决策依据仍是 vSMMU IDR) | **所有 S1 domain = 1**(2783 无条件路径) |
| guest STE.S2HA/S2HD | **0** | **0** | **0**(且 word5 不在转发范围) | **0**(内核无置位代码) |
| guest 内核 HTTU 特性 | FEAT_HA/HD 均不置 | 同左 | 同左 | FEAT_HA\|FEAT_HD |
| IOMMU_CAP_DIRTY_TRACKING | 不上报(请求被 EOPNOTSUPP 拒) | 同左 | 同左 | 上报 |
| 启动后变化 | 永不(IDR 只读、reset 幂等、迁移不传 idr[]) | 同左 | 同左 | — |

**一句话:判断 guest 填什么,只看 guest 的"世界观"——vSMMU 报告的 IDR0.HTTU,
而这个值在 QEMU 的所有模式下都恒为 0b00。CD.HA/HD 恒 0,因为唯一赋值语句的
上游能力条件恒假;STE.S2HA/S2HD 恒 0,因为这套内核根本没有写它们的代码。**

---

## 10. 关键代码位置索引

### QEMU 侧(`/home/akira/code/openeuler_qemu/qemu`)

| 文件:行号 | 内容 |
|---|---|
| `hw/arm/smmuv3-internal.h:42` | `FIELD(IDR0, HTTU, 6, 2)` 位定义 |
| `hw/arm/smmuv3-internal.h:581-582` | `STE_S2HD/STE_S2HA` 宏(零处使用) |
| `hw/arm/smmuv3-internal.h:642-643` | `CD_HD/CD_HA` 宏(bit 42/43) |
| `hw/arm/smmuv3-internal.h:76-79,108` | IDR 值宏(SIDSIZE/SSIDSIZE/CMDQS/EVENTQS/OAS) |
| `include/hw/registerfields.h:42-46/55-57/101-108` | FIELD / FIELD_EX32 / FIELD_DP32 宏定义 |
| `include/hw/arm/smmuv3.h:42` | `uint32_t idr[6]` 状态字段声明 |
| `hw/arm/smmuv3.c:261` | `smmuv3_nested_init_regs()` —— nested 覆盖入口 |
| `hw/arm/smmuv3.c:270-289` | 提前退出条件与宿主机信息读取 |
| `hw/arm/smmuv3.c:300-311` | IDR0 白名单(**HTTU 透传断点**) |
| `hw/arm/smmuv3.c:336` | `smmuv3_init_regs()` —— 唯一的仿真 IDR 写入点 |
| `hw/arm/smmuv3.c:340-354` | IDR0 字段构造(不含 HTTU;默认值 0x0C441019) |
| `hw/arm/smmuv3.c:773-786` | `decode_cd()` 拒绝 CD.HA/HD(C_BAD_CD) |
| `hw/arm/smmuv3.c:1424-1489` | `smmuv3_install_nested_ste()`(nested 转发,word0-3+掩码) |
| `hw/arm/smmuv3.c:2073-2075` | IDR 只读返回路径 |
| `hw/arm/smmuv3.c:2213` | `smmu_reset_hold()` → init_regs |
| `hw/arm/smmuv3.c:2225 / 2270` | `smmu_realize()` / `smmu_accel_realize()` |
| `hw/arm/smmuv3.c:2320-2349` | `vmstate_smmuv3`(不含 idr[]) |
| `hw/arm/smmu-common.c:836` | `smmu_dev_get_info()` → iommufd |
| `hw/arm/virt-acpi-build.c:811` | IORT Flags(仅 COHACC,无 HTTU override) |

### 内核侧(openEuler 6.6,`/home/akira/code/openeuler/kernel`)

| 文件:行号 | 内容 |
|---|---|
| `drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.h:399-400` | `CTXDESC_CD_0_TCR_HA(1<<43)` / `TCR_HD(1<<42)` |
| `drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c:1611-1614` | `arm_smmu_make_s1_cd()` —— **全内核唯一 HA/HD 赋值语句** |
| `drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c:2562-2566` | `arm_smmu_dbm_capable()`(FEAT_HD ∧ FEAT_COHERENCY) |
| `drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c:2715-2795` | `arm_smmu_domain_finalise()`:2755 脏跟踪 quirk / 2762 S2 EOPNOTSUPP / **2783 FEAT_HD 无条件 quirk** |
| `drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c:5550-5562` | probe:IORT HTTU_OVERRIDE → FEAT_HA/HD |
| `drivers/iommu/iommufd/hw_pagetable.c:126-127` | 脏跟踪请求的能力门(IOMMU_CAP_DIRTY_TRACKING) |
| `drivers/iommu/io-pgtable-arm.c:78,485-486` | `ARM_LPAE_PTE_DBM(1<<51)`,quirk 置位处 |
| `arch/arm64/include/asm/kvm_arm.h:131-134` | `VTCR_EL2_HDBSS(bit45)/HD(bit22)/HA(bit21)` |
| `arch/arm64/kvm/arm.c:152/167/200` | HDBSS 使能/清除逻辑(CPU stage-2,与 SMMU 无关) |
