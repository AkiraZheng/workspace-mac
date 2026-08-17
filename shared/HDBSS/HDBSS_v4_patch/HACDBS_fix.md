# KVM: arm64: HDBSS bits

## 添加了一个DBM标签到flags里

```diff
@@ -253,6 +255,7 @@ struct kvm_pgtable_mm_ops {
 enum kvm_pgtable_stage2_flags {
        KVM_PGTABLE_S2_IDMAP                    = BIT(0),
        KVM_PGTABLE_S2_AS_S1                    = BIT(1),
+       KVM_PGTABLE_S2_DBM                      = BIT(2),
 };
```

这里添加了一个DBM标签,用KVM_PGTABLE_S2_DBM替代了原先的KVM_PGTABLE_PROT_DBM

## 将添加DBM的地方包在了WRITABLE里

前面加prot flags的时候是不是可以少一次writable判断?

```diff
@@ -731,9 +731,13 @@ static int stage2_set_prot_attr(struct kvm_pgtable *pgt, enum kvm_p
gtable_prot p
        if (prot & KVM_PGTABLE_PROT_R)
                attr |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R;
 
-       if (prot & KVM_PGTABLE_PROT_W)
+       if (prot & KVM_PGTABLE_PROT_W) {
                attr |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
 
+               if (pgt->flags & KVM_PGTABLE_S2_DBM)
+                       attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
+       }
+
        if (!kvm_lpa2_is_enabled())
                attr |= FIELD_PREP(KVM_PTE_LEAF_ATTR_LO_S2_SH, sh);
 
@@ -1367,9 +1371,13 @@ int kvm_pgtable_stage2_relax_perms(struct kvm_pgtable *pgt, u64 a
ddr,
        if (prot & KVM_PGTABLE_PROT_R)
                set |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R;
 
-       if (prot & KVM_PGTABLE_PROT_W)
+       if (prot & KVM_PGTABLE_PROT_W) {
                set |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
 
+               if (pgt->flags & KVM_PGTABLE_S2_DBM)
+                       set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
+       }
+
        ret = stage2_set_xn_attr(prot, &xn);
        if (ret)
                return ret;
```

解答:这里只能在完全去掉ioctl后才能支持这种方式,而且,由于在s2 pgtable一开始就支持了添加了flag,就会导致所有可写页都加上DBM,但是实际上,我们如果HDBSS还没支持dirty ring的话,热迁移就会有问题,所以这里在 stage2_set_prot_attr() 中加一行过滤,既要过滤device页,又要过滤hdbss没有enable的场景：                                                                     
                                                                                        
```c
     if (prot & KVM_PGTABLE_PROT_W) {                                                   
         attr |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;                                        
         if ((pgt->flags & KVM_PGTABLE_S2_DBM) &&                                       
             !(prot & KVM_PGTABLE_PROT_DEVICE))       // ← 加这一行                     
             attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;                                       
     }    
```
## 改成现在软件vma init的时候添加DBM flags

```diff
@@ -1585,6 +1593,9 @@ int __kvm_pgtable_stage2_init(struct kvm_pgtable *pgt, struct kvm_
s2_mmu *mmu,
        if (!pgt->pgd)
                return -ENOMEM;
 
+       if (system_supports_hdbss())
+               flags |= KVM_PGTABLE_S2_DBM;
+
        pgt->ia_bits            = ia_bits;
        pgt->start_level        = start_level;
        pgt->mm_ops             = mm_ops;
```

# Enable eager hugepage splitting if HDBSS is available

这个patch相比之前的,增加了256 * 1024 * PAGE_SIZE,为什么不是单独用PAGE_SIZE?

```diff
diff --git a/arch/arm64/kvm/mmu.c b/arch/arm64/kvm/mmu.c
index 6c941aaa10c6..e086c01a9325 100644
--- a/arch/arm64/kvm/mmu.c
+++ b/arch/arm64/kvm/mmu.c
@@ -1027,8 +1027,12 @@ int kvm_init_stage2_mmu(struct kvm *kvm, struct kvm_s2_mmu *mmu, unsigned long t
        for_each_possible_cpu(cpu)
                *per_cpu_ptr(mmu->last_vcpu_ran, cpu) = -1;
 
-        /* The eager page splitting is disabled by default */
-       mmu->split_page_chunk_size = KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT;
+        /* The eager page splitting is disabled by default if system has no HDBSS */
+       if (system_supports_hdbss())
+               mmu->split_page_chunk_size = 256 * 1024 * PAGE_SIZE;
+       else
+               mmu->split_page_chunk_size = KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT;
+
        mmu->split_page_cache.gfp_zero = __GFP_ZERO;
 
        mmu->pgd_phys = __pa(pgt->pgd);
```

# Add system-wide FEAT_HACDBS detection

他在cpufeature前,为什么要在ftr_id_aa64mmfr4里面加一个ID_AA64MMFR4_EL1_HACDBS_SID_AA64MMFR4_EL1_HACDBS_SHIFT?

```diff
diff --git a/arch/arm64/kernel/cpufeature.c b/arch/arm64/kernel/cpufeature.c
index aa327eebaf1c..62f56bbd0a65 100644
--- a/arch/arm64/kernel/cpufeature.c
+++ b/arch/arm64/kernel/cpufeature.c
@@ -523,6 +523,7 @@ static const struct arm64_ftr_bits ftr_id_aa64mmfr3[] = {
 static const struct arm64_ftr_bits ftr_id_aa64mmfr4[] = {
        S_ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE, ID_AA64MMFR4_EL1_E2H0_SHIFT, 4, 0),
        ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE, ID_AA64MMFR4_EL1_NV_frac_SHIFT, 4, 0),
+       ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE, ID_AA64MMFR4_EL1_HACDBS_SHIFT, 4, 0),
        ARM64_FTR_END,
 };
```

解答:这里HDBSS不需要独立添加到ftr_id_aa64mmfr中,因为HDBSS已经登记在 ID_AA64MMFR1_EL1 的 HAFDBS 字段:

```
UnsignedEnum  3:0   HAFDBS
    0b0000   NI
    0b0001   AF
    0b0010   DBM
    0b0011   HAFT
    0b0100   HDBSS
```

而当前代码在cpufeature.c中已经定义了:

```c
static const struct arm64_ftr_bits ftr_id_aa64mmfr1[] = {
	ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE, ID_AA64MMFR1_EL1_ECBHB_SHIFT, 4, 0),
	//...
	ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE, ID_AA64MMFR1_EL1_HAFDBS_SHIFT, 4, 0),
	ARM64_FTR_END,
};
```
