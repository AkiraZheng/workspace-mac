# 0002: KVM: arm64: Add support to set the DBM attr during memory abort

## 基本信息

| 项目 | 内容 |
|------|------|
| Commit Hash | `a0b35601ddf9` |
| Author | eillon <yezhenyu2@huawei.com> |
| Date | 2026-05-22 |
| Subject | KVM: arm64: Add support to set the DBM attr during memory abort |
| Files Changed | `arch/arm64/include/asm/kvm_pgtable.h`, `arch/arm64/kvm/hyp/pgtable.c` |
| Lines Changed | +11 |

---

## Phase 1 分析

### 功能摘要
添加 DBM（Dirty Bit Modifier）属性支持，在 S2 PTE 中设置 DBM 位以支持硬件自动脏页追踪。

### 模块分类
KVM, mmu, stage-2, DBM

### 风险评估
- **风险等级**: 中
- **风险详情**: 修改页表权限处理逻辑，可能影响 VM 内存访问行为

### Revert 分析
- **Revert 等级**: 必须
- **Revert Commits**: 已在 Patch 0001 pre_revert 中完成全局 revert
- **Revert 原因**: 目标仓库已合入旧版本实现

### 依赖分析
- **高版本依赖**: 无
- **Bugfix 依赖**: 无
- **内部依赖**: 0001（KVM_PTE_LEAF_ATTR_HI_S2_DBM 定义）

### 重复检测
- **重复等级**: 高概率等效
- **重复详情**: 目标仓库已合入 DBM attr 设置: 74a1397438e0

### Review 评估
- **Review 等级**: 中
- **Review 原因**: 页表权限变更需确认 DBM 位设置时机和条件

### 冲突预判
- `arch/arm64/kvm/hyp/pgtable.c:stage2_set_prot_attr` 函数可能需适配

### 冒烟测试建议
- 启动 VM 测试 DBM 功能
- 验证 write fault 处理流程

---

## Phase 2 合入经验

### 执行状态
✅ done

### 冲突解决
- **冲突类型**: git am 失败（代码结构差异）
- **解决方式**: 手动应用
- **具体操作**:
  1. `git am --abort` 中止自动合入
  2. 手动编辑 `arch/arm64/kvm/hyp/pgtable.c`:
     - 在 `KVM_PTE_LEAF_ATTR_HI_S2_XN` 后添加 `KVM_PTE_LEAF_ATTR_HI_S2_DBM` 定义
     - 在 `stage2_set_prot_attr` 函数中添加 DBM 属性设置
     - 在 `kvm_pgtable_stage2_relax_perms` 函数中添加 DBM 属性设置
  3. 手动编辑 `arch/arm64/include/asm/kvm_pgtable.h`:
     - 在 `enum kvm_pgtable_prot` 中添加 `KVM_PGTABLE_PROT_DBM`
     - 更新注释

### 编译验证
- **编译命令**: `make ARCH=arm64 arch/arm64/kvm/hyp/pgtable.o`
- **编译结果**: ✅ 无错误
- **产物状态**: 正常

### Review 执行
- 未执行自动 review（reference 不存在）

---

## 完整 Diff

```diff
diff --git a/arch/arm64/include/asm/kvm_pgtable.h b/arch/arm64/include/asm/kvm_pgtable.h
index 4153b77d8aae..d9881c2981f9 100644
--- a/arch/arm64/include/asm/kvm_pgtable.h
+++ b/arch/arm64/include/asm/kvm_pgtable.h
@@ -178,6 +178,7 @@ enum kvm_pgtable_stage2_flags {
  * @KVM_PGTABLE_PROT_W:		Write permission.
  * @KVM_PGTABLE_PROT_R:		Read permission.
  * @KVM_PGTABLE_PROT_DEVICE:	Device attributes.
+ * @KVM_PGTABLE_PROT_DBM:	Dirty bit management attribute.
  * @KVM_PGTABLE_PROT_SW0:	Software bit 0.
  * @KVM_PGTABLE_PROT_SW1:	Software bit 1.
  * @KVM_PGTABLE_PROT_SW2:	Software bit 2.
@@ -190,6 +191,8 @@ enum kvm_pgtable_prot {
 
 	KVM_PGTABLE_PROT_DEVICE			= BIT(3),
 
+	KVM_PGTABLE_PROT_DBM			= BIT(4),
+
 	KVM_PGTABLE_PROT_SW0			= BIT(55),
 	KVM_PGTABLE_PROT_SW1			= BIT(56),
 	KVM_PGTABLE_PROT_SW2			= BIT(57),

diff --git a/arch/arm64/kvm/hyp/pgtable.c b/arch/arm64/kvm/hyp/pgtable.c
index d79feecc2f51..056b21a1ca92 100644
--- a/arch/arm64/kvm/hyp/pgtable.c
+++ b/arch/arm64/kvm/hyp/pgtable.c
@@ -44,6 +44,8 @@
 
 #define KVM_PTE_LEAF_ATTR_HI_S2_XN	BIT(54)
 
+#define KVM_PTE_LEAF_ATTR_HI_S2_DBM	BIT(51)
+
 #define KVM_PTE_LEAF_ATTR_HI_S1_GP	BIT(50)
 
 #define KVM_PTE_LEAF_ATTR_S2_PERMS	(KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R | \
@@ -711,6 +713,9 @@ static int stage2_set_prot_attr(struct kvm_pgtable *pgt, enum kvm_pgtable_prot p
 	if (prot & KVM_PGTABLE_PROT_W)
 		attr |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
 
+	if (prot & KVM_PGTABLE_PROT_DBM)
+		attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
+
 	attr |= FIELD_PREP(KVM_PTE_LEAF_ATTR_LO_S2_SH, sh);
 	attr |= KVM_PTE_LEAF_ATTR_LO_S2_AF;
 	attr |= prot & KVM_PTE_LEAF_ATTR_HI_SW;
@@ -1315,6 +1320,9 @@ int kvm_pgtable_stage2_relax_perms(struct kvm_pgtable *pgt, u64 addr,
 	if (prot & KVM_PGTABLE_PROT_W)
 		set |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
 
+	if (prot & KVM_PGTABLE_PROT_DBM)
+		set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
+
 	if (prot & KVM_PGTABLE_PROT_X)
 		clr |= KVM_PTE_LEAF_ATTR_HI_S2_XN;
```

---

## 总结

此 patch 添加 DBM 属性支持，依赖 0001，中等风险。代码结构差异导致 git am 失败，手动应用解决。编译通过。