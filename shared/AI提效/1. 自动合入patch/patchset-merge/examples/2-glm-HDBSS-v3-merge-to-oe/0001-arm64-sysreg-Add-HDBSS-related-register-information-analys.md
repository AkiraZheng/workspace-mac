# 0001: arm64/sysreg: Add HDBSS related register information

## 基本信息

| 项目 | 内容 |
|------|------|
| Commit Hash | `93c1ad725b72` |
| Author | eillon <yezhenyu2@huawei.com> |
| Date | 2026-05-22 |
| Subject | arm64/sysreg: Add HDBSS related register information |
| Files Changed | `arch/arm64/include/asm/esr.h`, `arch/arm64/tools/sysreg` |
| Lines Changed | +31 |

---

## Phase 1 分析

### 功能摘要
添加 HDBSS 寄存器定义（HDBSSBR_EL2/HDBSSPROD_EL2），为后续功能提供寄存器基础。

### 模块分类
arm64, sysreg, HDBSS

### 风险评估
- **风险等级**: 低
- **风险详情**: 仅添加寄存器定义，不涉及代码逻辑变更

### Revert 分析
- **Revert 等级**: 必须
- **Revert Commits**: 9 个（全局 revert 清单）
- **Revert 原因**: 目标仓库已合入旧版本（ioctl 502），需 revert 后合入新版本（ioctl 249）

### 依赖分析
- **高版本依赖**: 无
- **Bugfix 依赖**: 无
- **内部依赖**: 无（第一个 patch）

### 重复检测
- **重复等级**: 高概率等效
- **重复详情**: 目标仓库已合入相同功能寄存器定义: 16ab2a2fee8b

### Review 评估
- **Review 等级**: 低
- **Review 原因**: 寄存器定义标准化，无需深度 review

### 冒烟测试建议
- 检查 sysreg 文件编译
- 验证寄存器宏定义正确性

---

## Phase 2 合入经验

### 执行状态
✅ done

### 冲突解决
- **冲突类型**: git am 失败（sysreg 文件结构差异）
- **解决方式**: 手动应用
- **具体操作**: 
  1. `git am --abort` 中止自动合入
  2. 手动编辑 `arch/arm64/include/asm/esr.h` 在 ISS2 定义区域添加 HDBSSF
  3. 手动编辑 `arch/arm64/tools/sysreg` 在 DACR32_EL2 前添加 HDBSSBR_EL2 和 HDBSSPROD_EL2
  4. 生成 sysreg-defs.h 头文件

### 编译验证
- **编译命令**: `make ARCH=arm64 arch/arm64/kvm/arm.o`
- **编译结果**: ✅ 无错误
- **产物状态**: 正常

### Review 执行
- 未执行自动 review（reference 不存在）

---

## 完整 Diff

```diff
diff --git a/arch/arm64/include/asm/esr.h b/arch/arm64/include/asm/esr.h
index d5c30ee0985f..276eb39ed9a7 100644
--- a/arch/arm64/include/asm/esr.h
+++ b/arch/arm64/include/asm/esr.h
@@ -148,6 +148,8 @@
 #define ESR_ELx_CM 		(UL(1) << ESR_ELx_CM_SHIFT)
 
 /* ISS2 field definitions for Data Aborts */
+#define ESR_ELx_HDBSSF_SHIFT	(11)
+#define ESR_ELx_HDBSSF		(UL(1) << ESR_ELx_HDBSSF_SHIFT)
 #define ESR_ELx_TnD_SHIFT	(10)
 #define ESR_ELx_TnD 		(UL(1) << ESR_ELx_TnD_SHIFT)
 #define ESR_ELx_TagAccess_SHIFT	(9)

diff --git a/arch/arm64/tools/sysreg b/arch/arm64/tools/sysreg
index baded26ab7d7..de9fead05c7e 100644
--- a/arch/arm64/tools/sysreg
+++ b/arch/arm64/tools/sysreg
@@ -2477,6 +2477,35 @@ Sysreg	SMCR_EL2	3	4	1	2	6
 Fields	SMCR_ELx
 EndSysreg
 
+Sysreg	HDBSSBR_EL2	3	4	2	3	2
+Res0	63:56
+Field	55:12	BADDR
+Res0	11:4
+Enum	3:0	SZ
+	0b0000	4KB
+	0b0001	8KB
+	0b0010	16KB
+	0b0011	32KB
+	0b0100	64KB
+	0b0101	128KB
+	0b0110	256KB
+	0b0111	512KB
+	0b1000	1MB
+	0b1001	2MB
+EndEnum
+EndSysreg
+
+Sysreg	HDBSSPROD_EL2	3	4	2	3	3
+Res0	63:32
+Enum	31:26	FSC
+	0b000000	OK
+	0b010000	ExternalAbort
+	0b101000	GPF
+EndEnum
+Res0	25:19
+Field	18:0	INDEX
+EndSysreg
+
 Sysreg	DACR32_EL2	3	4	3	0	0
 Res0	63:32
 Field	31:30	D15
```

---

## 总结

此 patch 为 HDBSS 功能的基础寄存器定义，无依赖、低风险、编译通过。sysreg 文件位置差异导致 git am 失败，手动应用解决。