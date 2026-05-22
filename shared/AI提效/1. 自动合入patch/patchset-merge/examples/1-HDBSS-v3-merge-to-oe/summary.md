# Patchset Merge 汇总报告

## 基本信息
| 项 | 值 |
|----|-----|
| 来源 | /mnt/shared/originPatch/HDBSS_v3/ (v3 patchset from lore.kernel.org) |
| Patch 总数 | 5 |
| 合入成功 | 5 |
| 跳过 | 0 |
| 失败 | 0 |
| 目标分支 | patch-hdbss-v3 (基于 OLK-6.6) |
| Upstream | 无（降级模式） |

## 合入顺序与状态
| Seq | Patch | 状态 | 文件数 | 行数 | 适配说明 |
|-----|-------|------|--------|------|---------|
| 1 | 0001: sysreg HDBSS 寄存器定义 | ✅ done | 2 | +31 | 手动插入：GCSPR_EL2 上下文不存在 |
| 2 | 0002: DBM 属性支持 | ✅ done | 2 | +10 | API 差异：HI 宏移至 pgtable.c；KVM_PGTABLE_PROT_DBM=BIT(4) |
| 3 | 0003: FEAT_HDBSS cpufeature | ✅ done | 5 | +22 | KVM_CAP=249 保留上游号；system_supports_hdbss 使用 cpus_have_final_cap |
| 4 | 0004: HDBSS 核心实现 | ✅ done | 8 | +207 | 主要适配：guard()→rwlock；vcpu_load/put 替代 switch；kvm->arch.vtcr |
| 5 | 0005: ioctl 文档 | ✅ done | 1 | +16 | 插入 7.47 节 |

## Revert 记录
| Commit | 原因 | 关联 Patch |
|--------|------|-----------|
| 412a9d918ef7 (Revert b1d8169dd540) | 撤销现有 HDBSS bugfix 合并 (NVHE + memory leak) | 0004 |
| 08ba00f50518 (Revert fe4fa7481191) | 撤销现有 HDBSS feature 实现 (6 个 commit) | 0001-0005 |

## 关键适配说明

### 补丁 0004 适配点（目标内核 API 差异）
| 原始代码 | 目标内核适配 |
|---------|------------|
| `guard(write_lock_irqsave)(&kvm->mmu_lock)` | `unsigned long flags; write_lock_irqsave(...); ... write_unlock_irqrestore(...)` |
| `kvm_vcpu_load_vhe` / `kvm_vcpu_put_vhe` | `kvm_arch_vcpu_load` / `kvm_arch_vcpu_put` |
| `kvm->arch.mmu.vtcr` | `kvm->arch.vtcr` |
| `VTCR_EL2_HDBSS` | 新增宏 `#define VTCR_EL2_HDBSS (1ULL << 39)` |
| `esr_brk_comment()` 之后 | `esr_is_data_abort()` 之前 |
| `vncr_tlb` 字段后 | `reset_state` 字段后 |

## 编译验证总览
| Patch | 编译结果 | 修复次数 |
|-------|---------|---------|
| 0001 | ✅ 通过 | 0 |
| 0002 | ✅ 通过 | 0 |
| 0003 | ✅ 通过 | 0 |
| 0004 | ✅ 通过 | 2（vtcr 字段名、重复 TMM/RME case） |
| 0005 | ✅ 通过 | 0 |
| 终验 | ✅ `arch/arm64/boot/Image` 生成 | — |

## 全局风险汇总
- 高风险：0004 核心实现 — 涉及 KVM arm64 子系统多处修改，需在 HDBSS 硬件上进行功能验证
- 中风险：0003 cpufeature — 仅在 VHE 模式工作，需确认 `is_kernel_in_hyp_mode()` 逻辑
- 低风险：0001/0002/0005 — 寄存器定义、DBM 属性标志、文档

## 待处理事项
1. HDBSS 功能验证：需在 Armv9.5+ 硬件上测试脏页迁移场景
2. guard() 宏适配：后续可考虑为 rwlock 添加 DEFINE_LOCK_GUARD_1
3. switch.c 中的 __load_hdbss 已整合到 arm.c 的 vcpu_load 逻辑中
