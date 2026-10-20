---
name: ARM DBM/HDBSS Full Spec Text
description: Complete ARM DDI 0487 M.b spec text for D8.5 Hardware updates to translation tables (D8.5.2 dirty state, D8.5.2.3 HDBSS, D8.5.2.4 HACDBS) and D8.17 TLB maintenance — used for determining whether DBM on Device memory is architecturally permitted
type: reference
originSessionId: 58e26716-e9b1-4723-ad1a-8d22c2066e12
---
# ARM DDI 0487 M.b — DBM / HDBSS / Dirty State 相关章节全文

## D8.5 Hardware updates to the translation tables

### D8.5.2 The dirty state

**IHTJWZ** The dirty state is used to indicate a memory block or page has been modified. When hardware update of the dirty state is enabled, the descriptor DBM field indicates whether the descriptor is a candidate for hardware updates of the dirty state.

**RLRMSH** For the purpose of FEAT_HAFDBS dirty state management, a Block descriptor or Page descriptor can be described as having one of the following states:
- Non-writable.
- Writable-clean.
- Writable-dirty.

**RXSTDV** If a Block descriptor or Page descriptor is not writable-clean and not writable-dirty, then it is described as non-writable.

**RCLBGT** For a translation stage using Indirect permissions, software or hardware is permitted to manage the dirty state.

**RDQQCV** For a translation stage using Direct permissions, only hardware is permitted to manage the dirty state.

**RVRNVZ** For more information on managing the dirty state in hardware, see Hardware management of the dirty state.

**ICPTSY** For a stage 1 translation using Indirect permissions at ELx, if the Effective value of TCR_ELx.HD is 0, then dirty state is managed by software.

**IZCPYX** For stage 2 translations using Indirect permissions, if the Effective value of VTCR_EL2.HD is 0, then dirty state is managed by software.

**RQXCRT** For stage 1 translations using Indirect permissions that grant write permission, the following table shows the descriptor state based on the Block descriptor and Page descriptor nDirty field:

| nDirty field | Descriptor state |
|-------------|-----------------|
| 0 | Writable-dirty |
| 1 | Writable-clean |

Note: The polarity of the nDirty field matches the polarity of the AP[2] field used by Direct permissions.

**RXXBLY** For stage 2 translations using Indirect permissions that grant write permission:

| Dirty field | Descriptor state |
|-------------|-----------------|
| 0 | Writable-clean |
| 1 | Writable-dirty |

**RPPGMC** For write accesses translated by a writable-clean descriptor, if the descriptor dirty state is managed by software, then a Permission fault due to dirty state is generated.

---

### D8.5.2.1 Hardware management of the dirty state

**RQRTKG** All statements in this section require implementation of the OPTIONAL feature, FEAT_HAFDBS, which supports hardware update of the dirty state. FEAT_HAFDBS requires FEAT_HAF, which supports hardware update of the Access flag.

**IFLYZP** For stage 1 translations, if the Effective value of the corresponding TCR_ELx.HD is 1, then dirty state hardware management is enabled.

**IMHJZP** For stage 2 translations, if the Effective value of VTCR_EL2.HD is 1, then dirty state hardware management is enabled.

**IDLNSK** If a translation stage uses Direct permissions and hardware update of the dirty state is enabled, then the descriptor DBM field indicates whether the descriptor is a candidate for hardware updates of the dirty state.

**RPZFQC** For translations using Direct permissions, if the DBM field in a Block descriptor or Page descriptor is 0, then all of the following apply:
- For write accesses translated by the descriptor, the generation of Permission faults are unaffected by FEAT_HAFDBS.
- Hardware does not update the dirty state.

**RXZFQH** For each translation stage using Direct permissions, if all of the following apply, then a Block descriptor or Page descriptor is described as writable-clean:
- Dirty state hardware update is enabled at that translation stage.
- The descriptor DBM field is 1.
- For a descriptor used by stage 1 translation, the AP[2] field is 1 and this is the only reason that a Permission fault would be generated due to a write access if dirty state hardware management were disabled.
- For a descriptor used by stage 2 translation, the S2AP[1] field is 0 and this is the only reason that a Permission fault would be generated due to a write access if dirty state hardware management were disabled.

**RBRFGY** For each translation stage using Direct permissions, if all of the following apply, then a Block descriptor or Page descriptor is described as writable-dirty:
- Dirty state hardware update is enabled at that translation stage.
- The descriptor DBM field is 1.
- For a stage 1 translation, the AP[2] field is 0.
- For a stage 2 translation, the S2AP[1] field is 1.

**IHFBCN** If a translation stage uses Indirect permissions, then dirty state hardware management is not separately determined by each Block descriptor and Page descriptor. This is different from the case where a translation stage uses Direct permissions, and the DBM field indicates whether the descriptor is a candidate for dirty state hardware updates.

**IBFDYL** Only if a descriptor is writable-clean, then hardware can update the dirty state.

**RTYCNM** For write accesses translated by a writable-clean descriptor, if the descriptor dirty state is managed by hardware, then a Permission fault due to dirty state is not generated.

**RNSXRD** For write accesses translated by a writable-clean descriptor, if all of the following apply, then hardware updates that descriptor to writable-dirty:
- The descriptor dirty state is managed by hardware.
- The only reason that a Permission fault would be generated due to that write access would be if dirty state hardware management were disabled.

**RPQJJR** For a translation stage, when the dirty state is updated by hardware, the PE updates the corresponding descriptor in memory, in a coherent manner, using an atomic read-modify-write of that descriptor to change the descriptor from writable-clean to writable-dirty.

**RPRHKD** If the requirements to update both the Access flag and dirty state by hardware are met, the PE is permitted to update the Access flag to 1 as part of the same atomic read-modify-write of the descriptor that performs the dirty state update.

**IDSHLJ** For a translation stage, Access flag faults are reported with higher priority than Permission faults. Therefore, it is not permitted for hardware to update the dirty state so that a descriptor is writable-dirty but has the Access flag clear.

**RSGJBL** When the dirty state is updated by hardware, the PE is required to check that any copy of the descriptor cached in a TLB is not stale with regard to the descriptor in memory.

**IYZSVV** If the descriptor has changed, then the PE is required to use the new information from the descriptor in memory, regardless of whether the modified descriptor has a different OA, different attributes, or generates a fault.

**IWZRPC** For performance purposes, when the dirty state is updated by hardware, the PE should update or invalidate any TLB entry that contains a previously-cached copy of the descriptor. This is to prevent multiple writes by the PE from causing multiple updates to the descriptor.

**IHQBGN** Arm expects many implementations to cause a translation table walk to occur when dirty state hardware management causes an update of a translation table descriptor.

**RRNMLQ** If a write access translated by a writable-clean descriptor is performed architecturally, then hardware updates the dirty state of that descriptor.

**RDYCFD** If a write access translated by a writable-clean descriptor is not performed architecturally, then unless specified here hardware does not update the dirty state of that descriptor. In all of the following cases, hardware is permitted to update the dirty state while attempting to translate the explicit write access:
- The translation generates an MMU fault that is reported with lower priority than a Permission fault at that translation stage.
- **The access is non-speculative and the translation generates an Alignment fault only because the memory type indicated by the descriptor is Device, and the hardware update would have occurred if the Alignment fault was not generated.**
- The descriptor is for a stage 1 translation, the access is non-speculative, and the stage 2 translation of the OA from stage 1 generates a stage 2 MMU fault.
- The descriptor is used to translate accesses from the Statistical Profiling Buffer.
- The final OA from the translation generates a Granule Protection Check fault (GPC fault).
- FEAT_MTE_PERM is implemented and all of the following apply:
  - The descriptor is for a stage 2 translation.
  - The access is non-speculative.
  - The stage 2 translation generates a Permission fault due to the NoTagAccess attribute.
- FEAT_MTE_CANONICAL_TAGS is implemented and all of the following apply:
  - The descriptor is for a stage 1 translation.
  - The access is non-speculative.
  - The stage 1 translation generates a Permission fault due to a Canonical Tag Check operation.
- The descriptor is used to translate accesses from the Trace Buffer Unit.

**RBZXVS** If a tag write by an instruction that does not also write data is translated by a writable-clean descriptor, but the tag write effect is IGNORED due to one of the following reasons, then if all of the other requirements for a hardware update of Dirty state are met, it is CONSTRAINED UNPREDICTABLE whether hardware updates the dirty state of that descriptor:
- The stage 1 descriptor does not have the Tagged attribute.
- Allocation Tag Access is disabled for the instruction by SCR_EL3.ATA, HCR_EL2.ATA, or SCTLR_ELx.{ATA, ATA0}.

**RBDJJL** If both translation stages are enabled, and the conditions to update a stage 1 descriptor by hardware are met, then the stage 2 translation of the location holding that stage 1 descriptor results in one of the following:
- The stage 2 translation grants write permissions and the stage 1 hardware update occurs, including both of the following cases:
  - The stage 2 translation already grants write permission and does not need to be updated.
  - The stage 2 translation is writable-clean and is successfully updated to writable-dirty.
- The stage 2 translation generates a Permission fault due to lack of write access and the stage 1 hardware update does not occur.

**ITZTHF** If a speculative update of a stage 1 Access flag would otherwise be permitted, but the stage 2 translation of the stage 1 descriptor is read-only, then the speculative update of the stage 1 Access flag does not occur.

**RJCXVS** If all of the following apply, hardware can update the dirty state of a stage 2 descriptor even if the stage 1 descriptor is not updated, including the case where the stage 1 descriptor is not a Block descriptor or Page descriptor:
- Stage 1 hardware updates of the Access flag or dirty state are enabled.
- The stage 2 translation of a stage 1 translation table walk uses a writable-clean descriptor.

**RLXCKP** The dirty state hardware update mechanism does not affect the fault reporting priority except in all of the following cases:
- If all of the following stage 2 MMU faults are generated due to a non-speculative access that causes a stage 1 hardware update, then either fault is permitted to be reported:
  - That stage 1 hardware update generates a stage 2 MMU fault.
  - The stage 2 translation of the stage 1 OA generates a stage 2 MMU fault.
- **If a hardware update is permitted, that update is permitted to generate a synchronous External abort or an IMPLEMENTATION DEFINED abort caused by a memory type not supporting an atomic read-modify-write.**

**RQDRWL** If an instruction that generates more than one single-copy atomic memory access has a fault on some, but not all, of those memory accesses, then all of the following apply:
- All accesses that do not fault are permitted to cause hardware updates of the dirty state.
- For faulting accesses that meet the requirements for hardware updates of the dirty state, those accesses are also permitted to cause hardware updates of the dirty state.

---

### D8.5.2.2 Implications of enabling the dirty state management mechanism

**RYWCDD** All statements in this section require implementation of the OPTIONAL feature, FEAT_HAFDBS.

**RTTLCV** For stage 1 translations, translations using a descriptor in the writable-clean state are considered writable for the purposes of the corresponding SCTLR_ELx.WXN control.

**INSYYW** For stage 1 translations, if the corresponding SCTLR_ELx.WXN is 1, then all of the following apply:
- For a translation regime that supports a single privilege level, translations using a writable-clean descriptor are treated as execute-never.
- For a translation regime that supports two privilege levels, translations using a privileged writable-clean descriptor are treated as privileged execute-never.
- For a translation regime that supports two privilege levels, translations using an unprivileged writable-clean descriptor are treated as unprivileged execute-never.

**RNKLQN** For a translation regime that supports two privilege levels, translations using an unprivileged writable-clean descriptor are treated as privileged execute-never.

**RZYGHJ** Cache invalidation instructions and address translation instructions never cause a dirty state hardware update of either:
- The stage 1 Block descriptor or Page descriptor translating the address specified in the instruction.
- The stage 2 Block descriptor or Page descriptor translating the OA from the stage 1 translation.

**RMBXNP** Cache invalidation instructions and address translation instructions never cause a dirty state hardware update the stage 1 Block descriptor or Page descriptor translating the address specified in the instruction.

**RRKMHW** For the following instructions that require write permission, if the address specified in the instruction is translated by a writable-clean descriptor and hardware management of Dirty state is enabled for the corresponding stage of translation, then the descriptor is considered to grant write access and the hardware does not update the Dirty state of that descriptor:
- Data cache invalidation instruction, DC IVAC.
- Data cache and instruction cache maintenance instructions that are affected by FEAT_CMOW.
- Address translation instructions, AT S12E0W, AT S12E1W, AT S1E0W, AT S1E1W, AT S1E2W, AT S1E3W.

**RQXXXL** For all of the following cases, if the stage 1 descriptor is writable-clean, then it is **IMPLEMENTATION DEFINED** whether hardware updates the dirty state:
- A Store-Exclusive instruction to the memory location fails because the Exclusives monitor is not in the exclusive state.
- A GPC fault is generated on a write to the memory location.
- A synchronous External abort is generated on a write to the memory location.
- A Watchpoint exception is generated on a write to the memory location.
- A synchronous Tag check fault is generated on a write to the memory location.

**RSJQGP** For all of the following cases, if the stage 2 descriptor is writable-clean, then it is **IMPLEMENTATION DEFINED** whether hardware updates the dirty state:
- A Store-Exclusive instruction to the memory location fails because the Exclusives monitor is not in the exclusive state.
- A GPC fault is generated on a write to the memory location.
- A synchronous External abort is generated on a write to the memory location.
- A Watchpoint exception is generated on a write to the memory location.
- A synchronous Tag check fault is generated on a write to the memory location.

**RKLVVN** A hardware update of the dirty state performed by one PE does not require invalidation of any corresponding TLB entries in other PEs.

**RTXGHB** For a CAS or CASP instruction to an address translated by a writable-clean descriptor, if the comparison fails and the location is therefore not updated, then it is **CONSTRAINED UNPREDICTABLE** whether hardware updates the dirty state.

**RSMTCW** For an RCW or RCWS instruction to an address translated by a writable-clean descriptor, if the RCW checks or RCWS checks fail and the location is therefore not updated, then it is **CONSTRAINED UNPREDICTABLE** whether hardware updates the dirty state.

**RKTXCF** For a stage 2 writable-clean descriptor, if an atomic instruction to the address translated by the descriptor generates a stage 2 Permission fault only as a result of not having read permission, then it is **CONSTRAINED UNPREDICTABLE** whether hardware updates the dirty state.

---

### D8.5.2.3 Hardware dirty state tracking structure (HDBSS)

**INWXLF** The hardware dirty state tracking structure (HDBSS) keeps a record of dirtied stage 2 Block and Page descriptors, enabling EL2 software to retrieve this information without scanning translation tables.

**RRGTLS** All statements in this section require implementation of the OPTIONAL feature, FEAT_HDBSS.

**ITMYVQ** HDBSS is enabled only if VTCR_EL2.{HDBSS, HA, HD} are {1, 1, 1}.

**RGKFDY** If VTCR_EL2.HDBSS is 0, then all of the following apply:
- The PE does not update the HDBSS in response to a dirty state hardware update.
- The PE does not speculatively read the memory region configured by the HDBSSBR_EL2 fields.

**ISXBYL** All of the following apply to the HDBSS base address:
- It is a PA configured in HDBSSBR_EL2.BADDR.
- For encodings of HDBSSBR_EL2.SZ greater than 4KB, bits [(SZ+12-1):12] of HDBSSBR_EL2.BADDR are RES0, such that the base address is aligned to its size.

**RDBTZQ** The PA space of the HDBSS base address is determined by the Effective value of SCR_EL3.{NSE, NS}.

**IJRDPM** The HDBSS size is configured in HDBSSBR_EL2.SZ.

**RBWVKS** Each HDBSS entry is eight bytes.

**RQWSGD** HDBSS entry fields (Table D8-93):

| Bit position | Field | Comment |
|-------------|-------|---------|
| [63:56] | RES0 | - |
| [55:12] | IPA | The IPA translated by the stage 2 descriptor that was updated from writable-clean to writable-dirty. Aligned to the size of the Page or Block descriptor. Bits above the implemented physical address size are RES0. |
| [11] | NSIPA | For Secure state: 0 = Secure IPA, 1 = Non-secure IPA. For Realm and Non-secure states: RES0. |
| [10:4] | RES0 | - |
| [3:1] | TTWL | Translation table walk level at which the descriptor has been marked dirty. 3-bit two's complement signed integer. |
| [0] | Valid entry | 0 = invalid, 1 = valid. |

**RWZKFT** If HDBSS is enabled, then when hardware updates a stage 2 descriptor from writable-clean to writable-dirty, the PE writes to the HDBSS.

**IRYKVL** The index of the next eight-byte HDBSS entry to write is indicated by HDBSSPROD_EL2.INDEX.

**RHKCCN** The PE is permitted to mark HDBSS entries ahead of the HDBSSPROD_EL2.INDEX as zero.

**RPCTTC** When the PE writes an HDBSS entry, all the following occur:
- The IPA that caused hardware to update the stage 2 descriptor dirty state, and the associated NSIPA and TTWL, are written to the HDBSS using the current HDBSSPROD_EL2.INDEX. The write is done as a 64-bit single-copy atomic operation.
- The value of HDBSSPROD_EL2.INDEX is incremented by 1.

**RKFLNY** Accesses to the HDBSS use the same memory attributes as stage 2 translation table walks, including all of the following:
- The endianness configured by SCTLR_EL2.EE.
- The Normal memory type.
- The Cacheability and Shareability attributes configured by VTCR_EL2.{IRGN0, ORGN0, SH0}.
- If FEAT_MTE2 is implemented, accesses are always Tag Unchecked.
- If FEAT_MEC is implemented, the MECID used for stage 2 translation table walks.
- If FEAT_MPAM is implemented, the PARTID value, PMG value, and PARTID space used for stage 2 translation table walks.

**INMYYP** If FEAT_RME is implemented and GPC is enabled, accesses to the HDBSS are subject to Granule Protection Checks.

**RTCJKB** If the translation table update or the HDBSS update is observable to the PE that performed the write that caused these updates, then completion of a DSB that applies to both loads and stores on the same PE, at an Exception level where EL1&0 is out-of-context, guarantees observability of the other update.

**IKTVVZ** If the profiling buffer or trace buffer is enabled, further hardware updates of Dirty state may occur even if the EL1&0 translation regime is out-of-context. Disabling the buffer and executing PSB CSYNC or TSB CSYNC as appropriate, while the EL1&0 translation regime is out-of-context, before execution of a DSB that applies to both loads and stores, is sufficient to guarantee that all updates to the HDBSS are observable.

**RSTDKM** If any of the following apply, then there is no guarantee of order between the two updates described, and atomicity and coherency might be lost for the writes:
- The HDBSS entry and the translation table entry to be updated are at the same location.
- The write to the HDBSS and the write access being translated target the same location.
- The PE writes any HDBSS entry, and any other write not performed by the HDBSS is performed to any location in the HDBSS buffer.

**RCGCHP** On exception entry to ELx, where EL1&0 is out-of-context, outstanding HDBSS writes performed by the PE during execution at EL1&0 are guaranteed to be observable to memory accesses from ELx after completion of a DSB instruction that applies to both loads and stores.

**IXXFYP** Hardware increments of HDBSSPROD_EL2.INDEX are indirect writes, and are therefore not guaranteed to be observable to direct reads of HDBSSPROD_EL2 until completion of a context synchronization event.

**RRXCMY** The HDBSS is full when HDBSSPROD_EL2.INDEX is greater than or equal to 2^(HDBSSBR_EL2.SZ+12)/8.

**ILMSZL** If an HDBSS access generates an External abort or a GPC fault, and HDBSSPROD_EL2.FSC is updated to a non-zero value, then the update of the FSC field might not happen synchronously relative to some stage 2 hardware updates of the dirty state. Therefore, one or more HDBSS entries might be lost.

**RYHLRY** If the HDBSS is full and enabled, then the PE does not update any stage 2 descriptors from writable-clean to writable-dirty.

**RSTJMN** If the HDBSS is enabled, and either the HDBSS is full or HDBSSPROD_EL2.FSC is set to any value other than 0b000000, then all of the following apply:
- The PE cannot append entries to the HDBSS.
- Stage 2 dirty state hardware updates are prevented.
- Any access that requires a stage 2 dirty state hardware update generates a stage 2 Permission fault that is reported as it would be if VTCR_EL2.HD were 0. If the fault is reported in ESR_EL2, ESR_EL2.ISS2.HDBSSF is reported as 1.

**IKZMGK** MMU faults on speculative accesses are never reported. If the HDBSS is full and enabled, and this generates a stage 2 Permission fault as part of resolving an AT *E1* operation executed at EL2, it is reported in PAR_EL1 as a stage 2 Permission fault on a stage 1 translation table walk, at the level of stage 2 walk that experienced the fault.

#### D8.5.2.3.1 GPC fault on HDBSS access

**RLHLSD** If FEAT_RME is implemented and GPC is enabled, then when the hardware updates the stage 2 descriptor dirty state and the associated HDBSS access generates a GPC fault, all of the following apply:
- A GPC fault is reported.
- HDBSSPROD_EL2.INDEX points to the HDBSS entry that generated the fault.
- It is IMPLEMENTATION DEFINED which reporting mechanism is used:
  - A precise exception is reported as though the dirty state hardware update generated the GPC fault, and ESR_EL2.ISS2.HDBSSF is also set to 1.
  - The fault is reported in HDBSSPROD_EL2.FSC.

**IZRRMT** For an HDBSS access, if a GPC fault is reported precisely, then that fault can be reported as a Data Abort, Instruction Abort, or Granule Protection Check exception, and taken to EL2 or EL3.

#### D8.5.2.3.2 External aborts on HDBSS access

**RJHHQW** When an HDBSS write generates an External abort, HDBSSPROD_EL2.INDEX points to the entry that generated the fault, and it is IMPLEMENTATION DEFINED which reporting mechanism is used:
- A synchronous fault is generated with ESR_ELx.IFSC or ESR_ELx.DFSC indicating a synchronous External abort on a translation table walk or translation table hardware update. ESR_EL2.ISS2.HDBSSF is set to 1.
- The fault is reported by HDBSSPROD_EL2.FSC.

**RMWNLK** When an HDBSS write generates a synchronous External abort, the MMU is permitted to do a hardware update of the stage 2 dirty state.

**RQNJKV** When the hardware update of the stage 2 dirty state generates a synchronous External abort, or an Unsupported atomic hardware update fault, the MMU is permitted to write to the HDBSS.

---

### D8.5.2.4 Hardware accelerator for cleaning dirty state (HACDBS)

**IDRTDK** The hardware accelerator for cleaning dirty state (HACDBS) accelerates the process of updating Block and Page descriptors from writable-dirty to writable-clean.

**RQLGSL** All statements in this section require implementation of the OPTIONAL feature, FEAT_HACDBS.

**ICYLPL** The HACDBS is an HDBSS-like structure originating from either the same PE or different PEs. The format of entries in this structure is described in Table D8-93.

**IBGSDY** HACDBS processing is enabled only if HACDBSBR_EL2.EN is 1 and HCR_EL2.VM is 1.

**RBBWCH** When HACDBS processing is disabled by a changing HACDBSBR_EL2.EN from 1 to 0, completion of a DSB instruction guarantees that all outstanding translation table walks have completed.

**IBYRXM** All of the following apply to the HACDBS base address:
- It is a PA configured in HACDBSBR_EL2.BADDR.
- For encodings of HACDBSBR_EL2.SZ greater than 4KB, bits [(SZ+12-1):12] of HACDBSBR_EL2.BADDR are RES0.

**RHGVVT** The PA space of the HACDBS base address is determined by the Effective value of SCR_EL3.{NSE, NS}.

**ITQKLR** The HACDBS size is configured in HACDBSBR_EL2.SZ.

**RVRMKP** Each HACDBS entry is eight bytes.

**RSNFDZ** When processing an entry in the HACDBS, all of the following apply:
- The PE reads the HACDBS entry at the current value of HACDBSCONS_EL2.INDEX. The read is done as a 64-bit single-copy atomic operation.
- If the entry is valid, the PE decodes the HACDBS entry to determine the IPA, NSIPA and TTWL fields.
- For a valid entry, the PE uses a stage 2 translation table walk to locate the stage 2 Block or Page descriptor that translates the IPA.
- If any fault is generated, then HACDBS processing stops.
- If no fault is generated, then:
  - If the stage 2 descriptor is writable-dirty, then that descriptor is updated to writable-clean in a coherent manner, using an atomic read-modify-write.
  - If the stage 2 descriptor is writable-clean, it is not updated.
  - The value of HACDBSCONS_EL2.INDEX is incremented by 1.

**RKTPXV** For the purpose of processing HACDBS entries and qualifying a descriptor as writable-clean or writable-dirty in this context, it is not required that stage 2 dirty state hardware update be enabled. If stage 2 Direct permissions are used, then the descriptor DBM bit must be 1 for the descriptor to be considered writable-dirty. If stage 2 Indirect permissions are used, then the descriptor is writable-dirty if the Dirty bit in the descriptor is 1, and the permissions configured for the descriptor include Data Write or MMU Write permission.

**RZLNFF** If an entry in the HACDBS is not valid, then:
- The PE does not process the invalid entry.
- HACDBSCONS_EL2.INDEX is incremented by 1.

**IXZGCW** When the PE processes an entry and updates the corresponding stage 2 descriptor to writable-clean, the PE is not required to update any copy of that descriptor cached in a TLB.

**RBFTGZ** Accesses to the HACDBS use the same memory attributes as stage 2 translation table walks (Normal memory type, Cacheability/Shareability from VTCR_EL2).

**IPQQJG** If FEAT_RME is implemented and GPC is enabled, accesses to the HACDBS are subject to Granule Protection Checks.

**ITDFSP** For the purpose of cleaning HACDBS entries, Overlay permissions and the AssuredOnly property are ignored.

**RJSHZF** If the requirements are met, then the PE is permitted to process entries in the HACDBS ahead of the current value of HACDBSCONS_EL2.INDEX.

**RHWNDK** In the absence of an error, all entries preceding the entry pointed to by HACDBSCONS_EL2.INDEX have been successfully cleaned.

**RDPCSW** In the presence of an error, all the entries preceding the entry pointed to by HACDBSCONS_EL2.INDEX have been successfully cleaned and the entry at the current index caused a fault.

**IWWTCD** In the presence of an error, the PE is permitted to have successfully cleaned entries after the one pointed to by HACDBSCONS_EL2.INDEX.

**IRMLQL** If the HACDBS has empty entries, software can cause the PE to terminate processing before the end of the HACDBS is reached by programming the first empty entry with Valid=1 and TTWL set to a reserved value.

**RLFZLR** Hardware has finished processing the HACDBS when HACDBSCONS_EL2.INDEX is greater than or equal to 2^(HACDBSBR_EL2.SZ+12)/8.

**RDLWRN** The HACDBS interrupt request signal, HACDBSIRQ, is a level-sensitive interrupt request that is asserted when the Effective value of HACDBSBR_EL2.EN is 1, and one or more of the following are true:
- Hardware has finished processing the HACDBS.
- HACDBSCONS_EL2.ERR_REASON is set to a value other than 0b00.

**RRMVBG** If a Generic Interrupt Controller (GIC) is implemented, HACDBSIRQ must be a Private Peripheral Interrupt (PPI) in a multiprocessor system.

**RGQLDJ** When hardware has finished processing the HACDBS:
- The PE stops processing entries from the HACDBS.
- The HACDBSIRQ is asserted.

**RMRBXC** If HACDBSBR_EL2.EN is 1 and HACDBSCONS_EL2 does not indicate any error state, and software modifies HACDBSBR_EL2.{BADDR, SZ} or any field in HACDBSCONS_EL2, then any of the following are permitted to occur:
- The direct write is IGNORED.
- The fields in HACDBSCONS_EL2 become UNKNOWN.
- The address used for fetches of HACDBS entries is UNKNOWN.

---

## D8.17 TLB maintenance

**RRVJDB** For the purpose of TLB maintenance, a TLB entry is any structure that holds a translation table entry, including intermediate TLB caching structures and temporary working registers in translation table walk hardware.

**INDFND** When a translation table walk occurs, translation table entries that are permitted to be cached in a TLB might be held in TLB caching structures.

**RNWYRD** Entries held in a TLB are distinguished by translation context: Security state, translation regime, VMID, global/non-global, ASID.

**RFFWJK** TLBs, or TLB caching structures, are not guaranteed to remain coherent with changes to translation table entries, and are therefore distinct from data caches.

**RZYZYK** Indexing an intermediate TLB structure by the IA is permitted.

**RBKKRB** If FEAT_nTLBPA is not implemented, then indexing an intermediate TLB structure by PA and (for stage 1) IPA is also permitted.

**RTJQVP** If FEAT_nTLBPA is not implemented, any TLB maintenance instruction that applies to a PE with relevant context information ensures cached copies of translation table entries are invalidated for that PE in intermediate TLB structures indexed by PA or IPA.

**IPFNFJ** FEAT_nTLBPA permits software to determine the existence of intermediate TLB caching structures that are indexed by PA or IPA and perform TLB maintenance accordingly when it would otherwise not be required.

**RLGSCG** When a TLB maintenance instruction targets only stage 1 entries:
- The maintenance applies to any entries in caching structures that include stage 1 information used to translate the address or range being invalidated.
- If targeting a specific ASID, entries not tagged with that ASID are not invalidated.
- If stage 1 translation information has been collectively cached as smaller TLB entries (splintering), all entries containing that stage 1 information are invalidated.

**RTVTYQ** When a TLB maintenance instruction applies only to stage 2 entries:
- The maintenance applies to any entries in caching structures that include only stage 2 information.
- If stage 2 translation information has been cached as smaller TLB entries (splintering), all entries are invalidated.
- The maintenance is **not required** to apply to structures combining stage 1 and stage 2 information.

**RGNJPZ** When a TLB maintenance instruction applies to both stage 1 and stage 2 entries:
- The maintenance applies to any entries in caching structures that include stage 1 information.
- The maintenance applies to any entries in caching structures that include stage 2 information.
- The maintenance applies to structures combining stage 1 and stage 2 information.

**RPVVPF** TLB maintenance instructions that remove dirty state from stage 2 entries apply to entries that meet all of the following:
- The entry would be used for stage 2 translation (S2-only or combined S1+S2).
- The entry would be used with the current VMID.
- The entry would be used in an EL1&0 translation regime in the Security state selected by SCR_EL3.{NSE, NS}.

**RSYCZJ** If the Effective value of SCR_EL3.{NSE, NS} is {0, 0} and SCR_EL3.EEL2 is 0, then no TLB entries are affected by TLB maintenance instructions that only remove dirty state from stage 2 entries.

**RNNZGV** When a TLB maintenance instruction applies only to remove dirty state from stage 2 entries (consistent with clearing S2AP[1] or the Dirty bit if Indirect permissions are used):
- If VTCR_EL2.HD is 1 and the TLB entry was a cached copy of a writable-dirty descriptor, then a subsequent write access causes hardware to update the stage 2 dirty state, including checking that the cached copy is not stale.
- If Direct permissions are used at stage 2, and the TLB entry was a cached copy of a descriptor with write permission and DBM=0, then a subsequent write access causes a check to ensure the cached copy is not stale.
- If VTCR_EL2.HD is 0, then it is permitted for a subsequent write access to generate a stage 2 Permission fault.
- In all cases, over-invalidation is permitted, and a subsequent write access may cause a new translation table walk.

**RSWNLK** TLB maintenance operations that only remove dirty state from stage 2 entries apply regardless of the stage 2 Overlay permissions. Only the Base permissions in the TLB entries determine the effect.

**RGPPYH** When a translation table entry associated with a specific VMID or ASID is modified, software is required to invalidate the corresponding TLB entry.

**RVNRFW** When a System register field is modified and that field is permitted to be cached in a TLB, software is required to invalidate all TLB entries that might be affected.

**IWZCBG** When a translation table entry that generates a Translation fault, Address size fault, or Access flag fault is changed to one that does not fault:
- TLB invalidation is not required because an entry that generates a fault is never cached in a TLB.
- A Context synchronization event is required.

### D8.17.1 Using break-before-make when updating translation table entries

**RWHZWS** If multiple execution threads use the same translation tables, then when a translation table entry is modified in one or more of the following ways, the architecture requires software to use a break-before-make sequence:
- A change to the memory type, Shareability or Cacheability.
- The translation OA is changed and either/both of the old and new translations grant write permission, **including cases where the DBM bit is 1 and hardware updates of the dirty state is enabled.**
- The memory contents at the new OA do not match the previous OA.
- Changes to the block size (unless FEAT_BBML1/BBML2).
- A global entry is created that might overlap with non-global entries in a TLB.

**ITHWDH** Use of a break-before-make sequence guarantees prevention of:
- Multiple TLB entries for the same address.
- TLB caching breaking coherency.
- TLB caching breaking single-copy atomicity.
- TLB caching breaking ordering guarantees or uniprocessor semantics.
- TLB caching causing failure to clear Exclusives monitors.

**RDDMVT** A break-before-make sequence requires:
1. Replace the old translation table entry with an invalid entry.
2. Execute a DSB instruction.
3. Invalidate TLB entries with a broadcast TLB invalidation instruction.
4. Execute a DSB instruction.
5. Write the new translation table entry.
6. Execute a DSB instruction.

**IGXGZY** For a translation stage with AF hardware management enabled, if a translation table entry is modified and break-before-make is not followed, failures associated with AF hardware updates can occur.

**RRTBRL** **For a translation stage with dirty state hardware management enabled, if a translation table entry is modified and the break-before-make sequence is not followed, then all of the following failures associated with dirty state hardware updates can occur:**
- When a memory location is not written, hardware modifies the AP[2] or S2AP[1] descriptor bit.
- When a memory location is written, hardware does not modify the AP[2] or S2AP[1] descriptor bit.
- When hardware updates are followed by stores appearing later in program order, the ordering required is not followed.

**RFVQCK** If translation table entries are changed without appropriate TLB maintenance, including where break-before-make is required but not followed, it is possible that TLBs concurrently hold multiple different copies of those entries. In this situation:
- A TLB conflict abort may be detected (no access to memory, exception if architectural).
- The resulting behavior is **CONSTRAINED UNPREDICTABLE**, giving behavior consistent with translation using one (or an amalgamation of) the matching entries, but cannot permit access with permissions or attributes impossible in the current Security state/Exception level.

---

## 分析结论：DBM 能否加在 Device memory 上？

### 结论：ARM 规范没有明确禁止，但 DBM + Device memory 落在 IMPLEMENTATION DEFINED / CONSTRAINED UNPREDICTABLE 灰色地带

### 证据链

**证据 1 — 规范提到过 Device + dirty state 组合，但仅为边缘情况（RDYCFD）：**

> "The access is non-speculative and the translation generates an Alignment fault only because the memory type indicated by the descriptor is Device, and the hardware update would have occurred if the Alignment fault was not generated."

这说明 ARM 架构师考虑过 Device memory 上发生硬件 dirty update 的场景。但上下文是：unaligned write to Device 产生 Alignment fault，hardware **仍被允许**去更新 dirty state（因为 dirty update 是对 PTE 本身的操作，不是对 Device 地址）。这不是说 DBM on Device 是正常的，而是说在极端边缘情况下的行为——Alignment fault 已经产生了，硬件是否还去做 dirty update 无关紧要。

**证据 2 — 硬件 dirty update 是原子 RMW，Device memory 可能不支持（RQDRWL / RLXCKP）：**

> "If a hardware update is permitted, that update is permitted to generate a synchronous External abort or an **IMPLEMENTATION DEFINED abort caused by a memory type not supporting an atomic read-modify-write**."

这是最关键的证据。规范明确允许实现：**如果内存类型不支持原子 RMW，硬件更新可以产生 IMPLEMENTATION DEFINED abort**。而 Device memory 的典型特征就是：
- 不支持缓存
- 严格顺序访问
- **不支持原子 RMW 操作**（用于 dirty state update 的 read-modify-write of PTE）

因此，虽然规范没有直接写"禁止 DBM on Device memory"，但给出了实现可以 abort 的明确许可。

**证据 3 — DBM/HDBSS 整个设计上下文是 Normal memory：**

- 所有 HDBSS buffer 访问使用 **Normal memory** 属性（RKFLNY / RBFTGZ）
- DBM 更新要求 **atomic read-modify-write**（RPQJJR），这在 Normal cacheable memory 上才能正确实现
- `writable-clean` → `writable-dirty` 的状态转换模型是为可缓存的 RAM 页面设计的
- Device memory 的访问语义（不可缓存、严格有序、无推测执行）与 DBM 的硬件自动更新机制相矛盾

**证据 4 — 不规范行为导致 CONSTRAINED UNPREDICTABLE（RRTBRL / RFVQCK）：**

> "For a translation stage with dirty state hardware management enabled, if a translation table entry is modified and the break-before-make sequence is not followed, then failures associated with dirty state hardware updates can occur."

DBM on Device PTE 本质上是在没有合适 break-before-make 的情况下，将一个具有冲突属性（DBM + Device memory type）的 PTE 放入 TLB，属于不规范操作。

### 对 HDBSS Bug 分析的支撑

这完全解释了我们文档中记录的双平台差异：

| 平台 | DBM on Device 行为 | 规范依据 |
|------|-------------------|---------|
| **EVB (真实硅片)** | 容错，静默忽略 | 实现选择了"tolerant"路径——没有产生 abort，但也没有正确 dirty track |
| **FPGA** | 异常行为,设备状态错误 | 实现严格遵循规范——Device memory 不支持 RMW,行为 UNPREDICTABLE |

Kernel 侧的修复（`!device` 检查）是正确的：不管硬件实现如何，软件都不应该对 Device memory 设置 DBM，以避免进入 IMPLEMENTATION DEFINED 区域。
