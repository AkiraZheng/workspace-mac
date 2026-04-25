# vTLBID 寄存器定义 VTLBID<n>_EL2

> [VTLBID<n>_EL2, Virtual TLBI Domain Registers, n = 0 - 3](https://developer.arm.com/documentation/111107/2026-03/AArch64-Registers/VTLBID-n--EL2--Virtual-TLBI-Domain-Registers)

> [TLBI Domain ACPI table](https://github.com/tianocore/edk2/issues/11999)

# ACPI TLBI Domain Table

| 属性 | 内容 |
|------|------|
| **Title** | ACPI TLBI Domain table |
| **Status** | Draft |
| **Document** | ACPI Specification Version 6.next |
| **License** | SPDX-License-Identifier: CC-BY-4.0 |
| **Submitters** | Arm, TianoCore Community (https://www.tianocore.org) |

---

## Summary of the change

The Arm Architecture defines the FEAT_TLBID extension, allowing targeted TLB invalidations. This change introduces the TLBI Domain ACPI table, which describes the TLBI domain topology.

---

## Benefits of the change

OSPM will discover the TLBI Domain structure and thus be able to issue TLB invalidations more precisely.

---

## Impact of the change

Firmware, of platforms implementing Arm FEAT_TLBID, can present this ACPI TLBI table to describe the TLBI Domain hierarchy to OSPM. If OSPM performs TLBI domain invalidations, it must be altered to interpret the TLBI ACPI table.

---

## Detailed description of the change [normative updates]

- Strikethrough is for removal of existing content.
- Yellow is for re-formatting of existing content.
- Cyan is for new content.
- Pink is for cross-references.

---

### 5.2. ACPI System Description Tables

#### 5.2.6. System Description Table Header

**Table 5.5 — DESCRIPTION_HEADER Signatures for tables defined by ACPI**

| Signature | Description | Reference |
|-----------|-------------|-----------|
| "APIC" | Multiple APIC Description Table | Section 5.2.12 |
| ... | ... | ... |
| "SSDT" | Secondary System Description Table | Section 5.2.11.2 |
| "SVKL" | Storage Volume Key Data table in the Intel Trusted Domain Extensions. See Links to ACPI-Related Documents under the heading "Storage Volume Key Data". | |
| **"TLBI"** | **TLB Invalidate Domain Table** | **Section 5.2.38** |
| "XSDT" | Extended System Description Table | Section 5.2.8 |

---

### 5.2.38. Translation Lookaside Buffer Invalidate Domain Table

This section describes the Arm Translation Lookaside Buffer Invalidate Domain (TLBI) Table.

The Arm Architecture defines the FEAT_TLBID extension, which when present, allows the OSPM to target TLB invalidations to a specific domain. A TLBI domain can be contained in multiple parent domains.

The TLBI table lists all the PE and SMMU components and the TLBI Domains that each component belongs to.

---

**Table 5.Y — Translation Lookaside Buffer Invalidate Domain Table (TLBI) Format**

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
| Component list | -- | 40 | List of M TLBI Domain component sub-tables. The TLBI Domain component sub-table is defined in Table 5.Z. |

---

**Table 5.Z — TLBI Domain Component sub-table**

| Field | Byte Length | Byte Offset | Description |
|-------|-------------|-------------|-------------|
| Length | 4 | 0 | Length of this sub-table in bytes, including the Parent domain array. |
| Component | 4 | 4 | Component class: 1: PE, 2: SMMU. All other values are reserved. |
| Identifier | 4 | 8 | The identifier of the associated component: If type==1: the field contains the "ACPI Processor UID" of the corresponding GICC MADT entry. If type==2: the field contains the Identifier number of the corresponding SMMU entry in the IORT. |
| Number of Parent Domains (N) | 4 | 12 | Number of entries in the Parent domain array. |
| Parent Domain Offset | 4 | 16 | Offset in bytes, from the start of the TLBI table to the start of the Parent Domain Array. |
| Parent domain[N] | -- | 20 | Array of TLBI Domain IDs, with N entries. This component is contained within every domain ID listed in the array. Each Domain ID is represented by a 32-bit integer. |
