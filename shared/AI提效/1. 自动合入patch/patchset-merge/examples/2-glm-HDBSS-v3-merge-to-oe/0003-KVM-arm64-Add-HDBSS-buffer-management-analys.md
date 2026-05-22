# 0003: KVM: arm64: Add support for FEAT_HDBSS

## 基本信息

| 项目 | 内容 |
|------|------|
| Commit Hash | `29d4ace90b8c` |
| Author | eillon <yezhenyu2@huawei.com> |
| Date | 2026-05-22 |
| Subject | KVM: arm64: Add support for FEAT_HDBSS |
| Files Changed | `arch/arm64/include/asm/cpufeature.h`, `arch/arm64/kernel/cpufeature.c`, `arch/arm64/tools/cpucaps`, `include/uapi/linux/kvm.h`, `tools/include/uapi/linux/kvm.h` |
| Lines Changed | +20 |

---

## Phase 1 分析

### 功能摘要
添加 HDBSS 特性检测和初始化，定义 ARM64_HAS_HDBSS capability 和 system_supports_hdbss() 函数。

### 模块分类
KVM, cpufeature, HDBSS

### 风险评估
- **风险等级**: 低
- **风险详情**: 仅添加特性检测，不修改核心运行逻辑

### Revert 分析
- **Revert 等级**: 必须
- **Revert Commits**: 已在 Patch 0001 pre_revert 中完成全局 revert
- **Revert 原因**: 目标仓库已合入旧版本实现

### 依赖分析
- **高版本依赖**: 无
- **Bugfix 依赖**: 无
- **内部依赖**: 0001（寄存器定义）

### 重复检测
- **重复等级**: 高概率等效
- **重复详情**: 目标仓库已合入 HDBSS 特性检测: fe4fa7481191

### 特殊说明
- ioctl 编号差异：用户 patch 249 vs 目标仓库 502，revert 后将恢复为 249

### Review 评估
- **Review 等级**: 低
- **Review 原因**: 特性检测标准化实现

### 冒烟测试建议
- 检查 CPU feature list
- 验证 ID_AA64MMFR1_EL1 检测逻辑

---

## Phase 2 合入经验

### 执行状态
✅ done

### 冲突解决
- **冲突类型**: git am 失败（多文件位置差异）
- **解决方式**: 手动应用
- **具体操作**:
  1. `git am --abort` 中止自动合入
  2. 手动编辑各文件：
     - `arch/arm64/include/asm/cpufeature.h`: 在 `system_supports_haft()` 后添加 `system_supports_hdbss()`
     - `arch/arm64/kernel/cpufeature.c`: 
       - 在 `hvhe_possible()` 后添加 `has_vhe_hdbss()` 函数
       - 在 HAFT feature 后添加 HDBSS feature 定义
     - `arch/arm64/tools/cpucaps`: 在 HAFT 前添加 HAS_HDBSS
     - `include/uapi/linux/kvm.h`: 在 KVM_CAP_ARM_SUPPORTED_BLOCK_SIZES 后添加 KVM_CAP_ARM_HW_DIRTY_STATE_TRACK (249)
     - `tools/include/uapi/linux/kvm.h`: 同上

### 编译验证
- **编译命令**: `make ARCH=arm64 arch/arm64/kernel/cpufeature.o`
- **编译结果**: ✅ 无错误
- **产物状态**: 正常

### Review 执行
- 未执行自动 review（reference 不存在）

---

## 完整 Diff

```diff
diff --git a/arch/arm64/include/asm/cpufeature.h b/arch/arm64/include/asm/cpufeature.h
index 856c40ee00cf..d742bee816a0 100644
--- a/arch/arm64/include/asm/cpufeature.h
+++ b/arch/arm64/include/asm/cpufeature.h
@@ -888,6 +888,11 @@ static inline bool system_supports_haft(void)
 		cpus_have_final_cap(ARM64_HAFT);
 }
 
+static inline bool system_supports_hdbss(void)
+{
+	return cpus_have_final_cap(ARM64_HAS_HDBSS);
+}
+
 int do_emulate_mrs(struct pt_regs *regs, u32 sys_reg, u32 rt);

diff --git a/arch/arm64/kernel/cpufeature.c b/arch/arm64/kernel/cpufeature.c
index 414b9d28ecd1..aa433159adf2 100644
--- a/arch/arm64/kernel/cpufeature.c
+++ b/arch/arm64/kernel/cpufeature.c
@@ -2055,6 +2055,11 @@ static bool hvhe_possible(const struct arm64_cpu_capabilities *entry,
 	return cpuid_feature_extract_unsigned_field(val, ARM64_SW_FEATURE_OVERRIDE_HVHE);
 }
 
+static bool has_vhe_hdbss(const struct arm64_cpu_capabilities *entry, int scope)
+{
+	return is_kernel_in_hyp_mode() && has_cpuid_feature(entry, scope);
+}
+
 #ifdef CONFIG_ARM64_PAN
@@ -2819,6 +2824,13 @@ static const struct arm64_cpu_capabilities arm64_features[] = {
 		ARM64_CPUID_FIELDS(ID_AA64MMFR1_EL1, HAFDBS, HAFT)
 	},
 #endif
+	{
+		.desc = "Hardware Dirty state tracking structure (HDBSS)",
+		.type = ARM64_CPUCAP_SYSTEM_FEATURE,
+		.capability = ARM64_HAS_HDBSS,
+		.matches = has_vhe_hdbss,
+		ARM64_CPUID_FIELDS(ID_AA64MMFR1_EL1, HAFDBS, HDBSS)
+	},
 	{
 		.desc = "CRC32 instructions",

diff --git a/arch/arm64/tools/cpucaps b/arch/arm64/tools/cpucaps
index d8f2db273def..b0df1cfdf195 100644
--- a/arch/arm64/tools/cpucaps
+++ b/arch/arm64/tools/cpucaps
@@ -53,6 +53,7 @@ HAS_TLB_RANGE
 HAS_TWED
 HAS_VIRT_HOST_EXTN
 HAS_WFXT
+HAS_HDBSS
 HAFT
 HW_DBM

diff --git a/include/uapi/linux/kvm.h b/include/uapi/linux/kvm.h
index 1f67e4d6ff7b..d205283c4a7d 100644
--- a/include/uapi/linux/kvm.h
+++ b/include/uapi/linux/kvm.h
@@ -1200,6 +1200,7 @@ struct kvm_ppc_resize_hpt {
 #define KVM_CAP_COUNTER_OFFSET 227
 #define KVM_CAP_ARM_EAGER_SPLIT_CHUNK_SIZE 228
 #define KVM_CAP_ARM_SUPPORTED_BLOCK_SIZES 229
+#define KVM_CAP_ARM_HW_DIRTY_STATE_TRACK 249
 
 #define KVM_CAP_SEV_ES_GHCB 500

diff --git a/tools/include/uapi/linux/kvm.h b/tools/include/uapi/linux/kvm.h
index 3a2b617b6429..a80a67a0bf13 100644
--- a/tools/include/uapi/linux/kvm.h
+++ b/tools/include/uapi/linux/kvm.h
@@ -1192,6 +1192,7 @@ struct kvm_ppc_resize_hpt {
 #define KVM_CAP_COUNTER_OFFSET 227
 #define KVM_CAP_ARM_EAGER_SPLIT_CHUNK_SIZE 228
 #define KVM_CAP_ARM_SUPPORTED_BLOCK_SIZES 229
+#define KVM_CAP_ARM_HW_DIRTY_STATE_TRACK 249
 
 #ifdef KVM_CAP_IRQ_ROUTING
```

---

## 总结

此 patch 添加 HDBSS 特性检测，依赖 0001，低风险。多文件位置差异导致 git am 失败，手动应用解决。ioctl 编号 249。编译通过。