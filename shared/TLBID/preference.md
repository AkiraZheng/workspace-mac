# vTLBID 寄存器定义 VTLBID<n>_EL2

> [VTLBID<n>_EL2, Virtual TLBI Domain Registers, n = 0 - 3](https://developer.arm.com/documentation/111107/2026-03/AArch64-Registers/VTLBID-n--EL2--Virtual-TLBI-Domain-Registers)

> [TLBI Domain ACPI table](https://github.com/tianocore/edk2/issues/11999)

# ARM tlbid 实现的功能

简单来说，ARM 的 tlbid 是为了实现虚机中某个进程需要广播到的 tlbi 广播范围的细化，假设一个进程需要在[vcpu0,3,4]这几个 vcpu 中广播 tlbi，那么 kvm 中已经根据当前所有 vcpu 所在的 pcpu，建立了一个vdomain->pdomain的映射了（这个映射是找到当前vdomain下所有vcpu能被广播到所需要的那个最优的pdomain）

所以 qemu ACPI 刚开始要做的其实只是根据虚拟机中用户传进来的 vdomain 配置，将他改成所定义的 ACPI 形式。

# qemu启虚机指令

qemu 启虚机中，传入以下 tlbid 配置：

传入方式：domain 编号下管多少个 vCPU

```c
- tlbidomain domain_id=0,cpu=0-7
- tlbidomain domain_id=1,cpu=0-3
- tlbidomain domain_id=2,cpu=4-7
```

也就是 domain 0 是 vm 的全广播，domain 1 是 vm 的 0-7 个 vcpu 广播，domain 2 是 vm 的 0-15 个 vcpu 广播。

注意，传入的指令是当前 domain_id 下能包含多少个 vcpu，但是下面 ACPI 的规范中，他是通过将当前 vcpu 能映射到哪些domain中来定义的（Domain array[N]），也就是定义方式跟我们的qemu指令反着来，所以要注意做好转换。

# qemu ACPI 开发

qemu 启动虚机时，会把上述指令传入的配置，按照[附录： ACPI 规范](#附录-acpi-规范)，生成 ACPI TLBI Domain Table。

目标：coding

# 将 ACPI 信息传递给 KVM

```
kvm_vcpu_tlbidomain_config param: vcpu, vdomain_bitmap, vdomain_num

vcpu: configured vcpu
vdomain_bitmap: if this one vdomain has this vcpu, related bit should be set 1. this bitmap is 32bit.
vdomain_num: the number of vdomains.

e.g. if there are 4 vdomains, max_vcpu is 16, vdomain 0:0-15, vdomain 1:0-7, vdomain 2:8-15, vdomain 3:0-3. vdomain_bitmap we should have
are:

vcpu0: 0b1011
vcpu1: 0b1011
vcpu2: 0b1011
vcpu3: 0b1011
vcpu4: 0b0011
vcpu5: 0b0011
vcpu6: 0b0011
vcpu7: 0b0011
vcpu8: 0b0101
vcpu9: 0b0101
vcpu10: 0b0101
vcpu11: 0b0101
vcpu12: 0b0101
vcpu13: 0b0101
vcpu14: 0b0101
vcpu15: 0b0101

note: we should config one vCPU's vdomain before it actually run. Or at the first, we can
design taht all possible vCPU‘s vdomain should be set, before the first vCPU actually runs,
the implementation of this will be easier.
```



# 附录： ACPI 规范

## ACPI TLBI Domain Table

| 属性 | 内容 |
|------|------|
| **Title** | ACPI TLBI Domain table |
| **Status** | Draft |
| **Document** | ACPI Specification Version 6.next |
| **License** | SPDX-License-Identifier: CC-BY-4.0 |
| **Submitters** | Arm, TianoCore Community (https://www.tianocore.org) |

---

### Summary of the change

The Arm Architecture defines the FEAT_TLBID extension, allowing targeted TLB invalidations. This change introduces the TLBI Domain ACPI table, which describes the TLBI domain topology, and also introduces the TLBI Domain Hierarchy Level ACPI table, which describes the "hierarchy level" of each defined TLBI domain.

---

### Benefits of the change

OSPM will discover the TLBI Domain structure and thus be able to issue TLB invalidations more precisely.

---

### Impact of the change

Firmware, of platforms implementing Arm FEAT_TLBID, can present these ACPI TLBI tables to describe the TLBI Domain hierarchy to OSPM. If OSPM performs TLBI domain invalidations, it must be altered to interpret the TLBI ACPI tables.

---

### Detailed description of the change [normative updates]

- Strikethrough is for removal of existing content.
- Yellow is for re-formatting of existing content.
- Cyan is for new content.
- Pink is for cross-references.

---

#### 5.2. ACPI System Description Tables

##### 5.2.6. System Description Table Header

**Table 5.5 — DESCRIPTION_HEADER Signatures for tables defined by ACPI**

| Signature | Description | Reference |
|-----------|-------------|-----------|
| "APIC" | Multiple APIC Description Table | Section 5.2.12 |
| ... | ... | ... |
| "SSDT" | Secondary System Description Table | Section 5.2.11.2 |
| "SVKL" | Storage Volume Key Data table in the Intel Trusted Domain Extensions. See Links to ACPI-Related Documents under the heading "Storage Volume Key Data". | |
| **"TLBI"** | **TLB Invalidate Domain Table** | **Section 5.2.38** |
| **"TLBH"** | **TLB Invalidate Domain Hierarchy Level Table** | **Section 5.2.39** |
| "XSDT" | Extended System Description Table | Section 5.2.8 |

---

#### 5.2.38. Translation Lookaside Buffer Invalidate Domain Table

This section describes the Arm Translation Lookaside Buffer Invalidate Domain (TLBI) Table.

The Arm Architecture defines the FEAT_TLBID extension, which when present, allows the OSPM to target TLB invalidations to a specific domain. A TLBI domain can be contained in multiple parent domains.

The TLBI table lists all the PE and SMMU components and the TLBI Domains that each component belongs to.

**Table 5.W — Translation Lookaside Buffer Invalidate Domain Table (TLBI) Format**

| Field | Byte Length | Byte Offset | Description |
|-------|-------------|-------------|-------------|
| Signature | 4 | 0 | "TLBI" Signature for the TLBI Domain Table. |
| Length | 4 | 4 | The length of the table, in bytes, of the entire TLBI. |
| Revision | 1 | 8 | 1 |
| Checksum | 1 | 9 | The entire table, including the checksum field, must add to zero. |
| OEMID | 6 | 10 | An OEM-supplied string that identifies the OEM. |
| OEM Table ID | 8 | 16 | An OEM-supplied string that the OEM uses to identify this particular data table. |
| OEM Revision | 4 | 24 | An OEM-supplied revision number. |
| Creator ID | 4 | 28 | The Vendor ID of the utility that created this table. |
| Creator Revision | 4 | 32 | The revision of the utility that created this table. |
| Number of components (M) | 4 | 36 | The number of TLBI Domain components in the Component list. |
| Component list | -- | 40 | List of M TLBI Domain component sub-tables. The TLBI Domain component sub-table is defined in Table 5.X. |

---

**Table 5.X — TLBI Domain Component sub-table**

| Field | Byte Length | Byte Offset | Description |
|-------|-------------|-------------|-------------|
| Type | 2 | 0 | Component type: 1: PE, 2: SMMU. All other values are reserved. |
| Reserved | 2 | 2 | |
| Length | 4 | 4 | Length of this sub-table in bytes, including the Parent domain array. |
| Identifier | 4 | 8 | The identifier of the associated component: If Component type==1: the field contains the "ACPI Processor UID" of the corresponding GICC MADT entry. If Component type==2: the field contains the Identifier number of the corresponding SMMU entry in the IORT. |
| Number of Domains (N) | 4 | 12 | Number of entries in the Domain array. |
| Domain array offset | 4 | 16 | Offset in bytes, from the start of the TLBI table to the start of the Domain array. |
| Domain array[N] | -- | 20 | Array of TLBI Domain IDs, with N entries. This component is contained within every domain ID listed in the array. Each Domain ID is represented by a 32-bit integer. |

---

#### 5.2.39. Translation Lookaside Buffer Invalidate Domain Hierarchy Level Table

This section describes the Arm Translation Lookaside Buffer Invalidate Domain Hierarchy Level (TLBH) Table.

A TLBI domain corresponds to at least a group of PEs, and at most every socket in the system. To aide in synchronising invalidations, a hierarchy level is defined, and each TLBI domain has an assigned level.

The TLBH table lists all TLBI Domains and the hierarchy level of each domain.

**Table 5.Y — Translation Lookaside Buffer Invalidate Domain Hierarchy Level Table (TLBH) Format**

| Field | Byte Length | Byte Offset | Description |
|-------|-------------|-------------|-------------|
| Signature | 4 | 0 | "TLBH" Signature for the TLBI Domain Hierarchy Level Table. |
| Length | 4 | 4 | The length of the table, in bytes, of the entire TLBH. |
| Revision | 1 | 8 | 1 |
| Checksum | 1 | 9 | The entire table, including the checksum field, must add to zero. |
| OEMID | 6 | 10 | An OEM-supplied string that identifies the OEM. |
| OEM Table ID | 8 | 16 | An OEM-supplied string that the OEM uses to identify this particular data table. |
| OEM Revision | 4 | 24 | An OEM-supplied revision number. |
| Creator ID | 4 | 28 | The Vendor ID of the utility that created this table. |
| Creator Revision | 4 | 32 | The revision of the utility that created this table. |
| Number of mappings (M) | 4 | 36 | The number of TLBI Domain Hierarchy Level Mappings in the Mapping list. |
| Mapping list | -- | 40 | List of M TLBI Domain Hierarchy Level Mapping sub-tables. The TLBI Domain Hierarchy Level Mapping sub-table is defined in Table 5.Z. |

---

**Table 5.Z — TLBI Domain Hierarchy Level Mapping sub-table**

| Field | Byte Length | Byte Offset | Description |
|-------|-------------|-------------|-------------|
| TLBI Domain | 4 | 0 | TLBI Domain Identifier |
| Hierarchy Level | 4 | 4 | TLBI Domain Hierarchy Level. Currently defined levels, and their meanings, are as follows: 0: Root, 1: Socket Pair, 2: Socket, 3: Chiplet Quad, 4: Chiplet Pair, 5: Chiplet, 6: Leaf Pair, 7: Leaf. NOTE: A "Leaf" is a block of up to 32 PEs, and the finest granularity that a TLBI can be directed to. |
