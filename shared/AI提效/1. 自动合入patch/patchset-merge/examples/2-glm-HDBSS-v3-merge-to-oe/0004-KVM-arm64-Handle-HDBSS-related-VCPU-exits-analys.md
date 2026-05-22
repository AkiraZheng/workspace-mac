# 0004: KVM: arm64: Enable HDBSS support and handle HDBSSF events

## 基本信息

| 项目 | 内容 |
|------|------|
| Commit Hash | `7c79d8212f3e` |
| Author | eillon <yezhenyu2@huawei.com> |
| Date | 2026-05-22 |
| Subject | KVM: arm64: Enable HDBSS support and handle HDBSSF events |
| Files Changed | 8 files（详见 diff） |
| Lines Changed | +226 |

---

## Phase 1 分析

### 功能摘要
启用 HDBSS 支持，实现 buffer 管理、flush 逻辑、fault handling（buffer full/external abort/GPF）。

### 模块分类
KVM, HDBSS, mmu, vhe, fault-handling

### 风险评估
- **风险等级**: 高
- **风险详情**: 修改 KVM 核心运行逻辑（vcpu_load/put、guest_abort handling），添加新 fault 处理路径

### Revert 分析
- **Revert 等级**: 必须
- **Revert Commits**: 已在 Patch 0001 pre_revert 中完成全局 revert
- **Revert 原因**: 目标仓库已合入旧版本实现（含 bugfix）

### 依赖分析
- **高版本依赖**: 无
- **Bugfix 依赖**: 无
- **内部依赖**: 0001, 0002, 0003

### 重复检测
- **重复等级**: 高概率等效
- **重复详情**: 目标仓库已合入 buffer 管理、fault handling: 6d60015590c3, bd6106e348d7

### 冲突预判
- `arch/arm64/kvm/arm.c:kvm_cap_arm_enable_hdbss` 函数需适配
- `arch/arm64/kvm/mmu.c:kvm_flush_hdbss_buffer` 函数需适配
- `arch/arm64/kvm/hyp/vhe/switch.c:vcpu load/put` 路径

### Review 评估
- **Review 等级**: 高
- **Review 原因**: 涉及 VM exit 处理、内存管理、同步机制，需深度 review

### 冒烟测试建议
- 启动 VM + live migration 测试
- 验证 HDBSSF fault handling
- 测试 buffer flush 机制

---

## Phase 2 合入经验

### 执行状态
✅ done

### 冲突解决
- **冲突类型**: git am 失败（8 个文件位置差异）
- **解决方式**: 手动应用
- **具体操作**:
  1. `git am --abort` 中止自动合入
  2. 手动编辑各文件（共 8 个）：
     - `arch/arm64/include/asm/esr.h`: 添加 `esr_iss2_is_hdbssf()` 函数
     - `arch/arm64/include/asm/kvm_host.h`: 
       - 添加 `KVM_REQ_FLUSH_HDBSS` request
       - 添加 `HDBSS_ENTRY_VALID/IPA` 宏
       - 添加 `kvm_arm_vcpu_free_hdbss()` 声明
       - 在 `kvm_arch` 中添加 `enable_hdbss` 字段
       - 添加 `struct vcpu_hdbss_state` 定义
       - 在 `kvm_vcpu_arch` 中添加 `hdbss` 字段
     - `arch/arm64/include/asm/kvm_mmu.h`: 添加 `kvm_flush_hdbss_buffer()` 声明
     - `arch/arm64/include/asm/sysreg.h`: 添加 HDBSS 相关宏定义（注意：SZ 常量由 sysreg 自动生成，不手动定义）
     - `arch/arm64/kvm/arm.c`: 
       - 添加 `kvm_arm_vcpu_free_hdbss()` 函数
       - 添加 `kvm_cap_arm_enable_hdbss()` 函数
       - 在 enable_cap switch 中添加 KVM_CAP_ARM_HW_DIRTY_STATE_TRACK case
       - 在 check_extension 中添加 capability check
       - 在 check_vcpu_requests 中添加 KVM_REQ_FLUSH_HDBSS 处理
     - `arch/arm64/kvm/hyp/vhe/switch.c`: 
       - 添加 `__load_hdbss()` 函数
       - 在 vcpu load 路径调用 `__load_hdbss()`
     - `arch/arm64/kvm/mmu.c`: 
       - 添加 `HDBSSPROD_EL2_FSC_*` 常量
       - 添加 `kvm_flush_hdbss_buffer()` 函数
       - 添加 `kvm_handle_hdbss_fault()` 函数
       - 在 `user_mem_abort` 中添加 DBM 属性设置
       - 在 `kvm_handle_guest_abort` 入口添加 HDBSSF 检查
     - `arch/arm64/kvm/reset.c`: 在 vcpu_destroy 中添加 HDBSS buffer 释放

### 后续修复
- 提交后发现 sysreg.h 中 `HDBSSBR_EL2_SZ_*` 常量与自动生成的定义重复
- 创建 fix commit `b812b22ac237` 移除手动定义

### 编译验证
- **编译命令**: `make ARCH=arm64 arch/arm64/kvm/arm.o arch/arm64/kvm/mmu.o arch/arm64/kvm/reset.o arch/arm64/kvm/hyp/vhe/switch.o`
- **编译结果**: ✅ 无错误（修复重复定义后）
- **产物状态**: 正常

### Review 执行
- 未执行自动 review（reference 不存在）

---

## 完整 Diff

```diff
diff --git a/arch/arm64/include/asm/esr.h b/arch/arm64/include/asm/esr.h
index 276eb39ed9a7..a75188f8179a 100644
--- a/arch/arm64/include/asm/esr.h
+++ b/arch/arm64/include/asm/esr.h
@@ -391,6 +391,11 @@
 #ifndef __ASSEMBLY__
 #include <asm/types.h>
 
+static inline bool esr_iss2_is_hdbssf(unsigned long esr)
+{
+	return ESR_ELx_ISS2(esr) & ESR_ELx_HDBSSF;
+}
+
 static inline bool esr_is_data_abort(unsigned long esr)

diff --git a/arch/arm64/include/asm/kvm_host.h b/arch/arm64/include/asm/kvm_host.h
index ac4e59256f8e..5ac059e6e647 100644
--- a/arch/arm64/include/asm/kvm_host.h
+++ b/arch/arm64/include/asm/kvm_host.h
@@ -55,12 +55,17 @@
 #define KVM_REQ_RELOAD_WFI_TRAPS       KVM_ARCH_REQ(9)
+#define KVM_REQ_FLUSH_HDBSS			KVM_ARCH_REQ(10)

+#define HDBSS_ENTRY_VALID BIT(0)
+#define HDBSS_ENTRY_IPA GENMASK_ULL(55, 12)

+void kvm_arm_vcpu_free_hdbss(struct kvm_vcpu *vcpu);

+	bool enable_hdbss;

+struct vcpu_hdbss_state {
+	phys_addr_t base_phys;
+	u32 size;
+	u32 next_index;
+};

+	struct vcpu_hdbss_state hdbss;

diff --git a/arch/arm64/kvm/arm.c b/arch/arm64/kvm/arm.c
index 067348105655..bf746aea1346 100644
--- a/arch/arm64/kvm/arm.c
+++ b/arch/arm64/kvm/arm.c
@@ -130,6 +130,81 @@ int kvm_arch_vcpu_should_kick(struct kvm_vcpu *vcpu)
+void kvm_arm_vcpu_free_hdbss(struct kvm_vcpu *vcpu)
+{
+	struct page *hdbss_pg;
+	hdbss_pg = phys_to_page(vcpu->arch.hdbss.base_phys);
+	if (hdbss_pg)
+		__free_pages(hdbss_pg, vcpu->arch.hdbss.size);
+	vcpu->arch.hdbss.size = 0;
+}
+
+static int kvm_cap_arm_enable_hdbss(struct kvm *kvm, struct kvm_enable_cap *cap)
+{
+	// ... (86 lines, full buffer management)
+}

// capability handling, vcpu requests handling...

diff --git a/arch/arm64/kvm/hyp/vhe/switch.c b/arch/arm64/kvm/hyp/vhe/switch.c
index 821e366b54f2..32e09b90ff40 100644
--- a/arch/arm64/kvm/hyp/vhe/switch.c
+++ b/arch/arm64/kvm/hyp/vhe/switch.c
@@ -89,6 +89,23 @@ static void __activate_traps(struct kvm_vcpu *vcpu)
+NOKPROBE_SYMBOL(__activate_traps);
+
+static void __load_hdbss(struct kvm_vcpu *vcpu)
+{
+	struct kvm *kvm = vcpu->kvm;
+	u64 br_el2, prod_el2;
+	if (!kvm->arch.enable_hdbss)
+		return;
+	br_el2 = HDBSSBR_EL2(vcpu->arch.hdbss.base_phys, vcpu->arch.hdbss.size);
+	prod_el2 = vcpu->arch.hdbss.next_index;
+	write_sysreg_s(br_el2, SYS_HDBSSBR_EL2);
+	write_sysreg_s(prod_el2, SYS_HDBSSPROD_EL2);
+	isb();
+}

// vcpu load path: __load_hdbss(vcpu);

diff --git a/arch/arm64/kvm/mmu.c b/arch/arm64/kvm/mmu.c
index 016bde6cdffd..4a5a741ab567 100644
--- a/arch/arm64/kvm/mmu.c
+++ b/arch/arm64/kvm/mmu.c
@@ -1667,6 +1667,9 @@
+	if (writable && kvm->arch.enable_hdbss && logging_active)
+		prot |= KVM_PGTABLE_PROT_DBM;

+#define HDBSSPROD_EL2_FSC_MASK		GENMASK(31, 26)
+#define HDBSSPROD_EL2_FSC_OK		0
+#define HDBSSPROD_EL2_FSC_ExternalAbort	(0b010000 << 26)
+#define HDBSSPROD_EL2_FSC_GPF		(0b101000 << 26)
+
+void kvm_flush_hdbss_buffer(struct kvm_vcpu *vcpu)
+{
+	// ... (72 lines, flush logic)
+}
+
+static int kvm_handle_hdbss_fault(struct kvm_vcpu *vcpu)
+{
+	// ... (fault handling)
+}

// guest abort entry: HDBSSF check

diff --git a/arch/arm64/kvm/reset.c b/arch/arm64/kvm/reset.c
index 89bb3cc4ee0e..6e33d769f56f 100644
--- a/arch/arm64/kvm/reset.c
+++ b/arch/arm64/kvm/reset.c
@@ -181,6 +181,9 @@ void kvm_arm_vcpu_destroy(struct kvm_vcpu *vcpu)
+	if (vcpu->kvm->arch.enable_hdbss)
+		kvm_arm_vcpu_free_hdbss(vcpu);
```

---

## 总结

此 patch 为核心实现，依赖 0001-0003，高风险。8 个文件位置差异导致 git am 失败，手动应用解决。编译通过后发现重复定义问题，创建 fix commit 修复。