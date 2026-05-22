# 0005: KVM: arm64: Document HDBSS ioctl

## 基本信息

| 项目 | 内容 |
|------|------|
| Commit Hash | `f447cb729f5e` |
| Author | eillon <yezhenyu2@huawei.com> |
| Date | 2026-05-22 |
| Subject | KVM: arm64: Document HDBSS ioctl |
| Files Changed | `Documentation/virt/kvm/api.rst` |
| Lines Changed | +16 |

---

## Phase 1 分析

### 功能摘要
添加 KVM_CAP_ARM_HW_DIRTY_STATE_TRACK ioctl 文档说明。

### 模块分类
Documentation, KVM, HDBSS

### 风险评估
- **风险等级**: 低
- **风险详情**: 仅文档变更，不影响代码

### Revert 分析
- **Revert 等级**: 必须
- **Revert Commits**: 已在 Patch 0001 pre_revert 中完成全局 revert
- **Revert 原因**: 目标仓库已有文档说明

### 依赖分析
- **高版本依赖**: 无
- **Bugfix 依赖**: 无
- **内部依赖**: 0003, 0004

### 重复检测
- **重复等级**: 高概率等效
- **重复详情**: 目标仓库已有文档说明

### Review 评估
- **Review 等级**: 低
- **Review 原因**: 文档内容需确认 ioctl 参数说明准确

### 冒烟测试建议
- 检查文档格式
- 验证 ioctl 说明与实现一致

---

## Phase 2 合入经验

### 执行状态
✅ done

### 冲突解决
- **冲突类型**: git am 失败（文档位置差异）
- **解决方式**: 手动应用
- **具体操作**:
  1. `git am --abort` 中止自动合入
  2. 查找文档位置：第 7949 行附近（section 7 和 8 交界）
  3. 手动编辑 `Documentation/virt/kvm/api.rst`：
     - 在 section 7.38 (KVM_CAP_ARM_RME) 后添加 section 7.39
     - 添加完整的 ioctl 文档说明

### 编译验证
- **编译命令**: 文档无需编译
- **编译结果**: ✅ 无错误
- **产物状态**: 正常

### Review 执行
- 未执行自动 review（reference 不存在）

---

## 完整 Diff

```diff
diff --git a/Documentation/virt/kvm/api.rst b/Documentation/virt/kvm/api.rst
index 470b7da2ae41..56d66a53fcc7 100644
--- a/Documentation/virt/kvm/api.rst
+++ b/Documentation/virt/kvm/api.rst
@@ -7948,6 +7948,22 @@ Used to configure and set up the memory for a Realm. The available actions are:
                                   enter the realm until it has been activated.
 ================================= =============================================
 
+7.39 KVM_CAP_ARM_HW_DIRTY_STATE_TRACK
+-------------------------------------
+
+:Architectures: arm64
+:Type: VM
+:Parameters: args[0] is the allocation order determining HDBSS buffer size
+             args[1] is 0 to disable, 1 to enable HDBSS
+:Returns: 0 on success, negative value on failure
+
+Enables hardware-assisted dirty page tracking via the Hardware Dirty State
+Tracking Structure (HDBSS).
+
+When live migration is initiated, userspace can enable this feature by
+setting KVM_CAP_ARM_HW_DIRTY_STATE_TRACK through IOCTL. KVM will allocate
+per-vCPU HDBSS buffers.
+
 8. Other capabilities.
 ======================
```

---

## 总结

此 patch 为文档说明，依赖 0003-0004，低风险。文档位置差异导致 git am 失败，手动应用解决。无编译验证需求。