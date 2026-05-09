# 关于"迁移时fault添加DBM"方案的Argument

## 背景

当前HDBSS设计：在迁移过程中，Guest写内存触发page fault时，在`user_mem_abort()`中添加DBM标签。

替代方案探讨：是否应该在页创建时就添加DBM标签？

---

## 核心论点：迁移时fault添加DBM的开销是可接受的

### 论点0（必要条件）：禁用HDBSS时必须清除DBM

**当前设计的问题**：
```
启用HDBSS时：添加DBM
禁用HDBSS时：不清除DBM ❌

问题：
    - DBM位保留在页表中
    - VTCR_EL2.HDBSS=0时Guest写内存行为不符合预期
```

**解决方案**：

在禁用HDBSS时，需要遍历所有设置了DBM的页，清除DBM位：

```c
if (!enable) {
    // 1. 清除VTCR_EL2的HDBSS位
    kvm->arch.mmu.vtcr &= ~(VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA);

    // 2. 遍历所有memslot，清除所有页的DBM位
    for (每个memslot) {
        for (每个页) {
            if (PTE.DBM == 1) {
                clear DBM;
            }
        }
    }

    // 3. 释放buffer
    kvm_for_each_vcpu(i, vcpu, kvm)
        kvm_arm_vcpu_free_hdbss(vcpu);

    kvm->arch.enable_hdbss = false;
}
```

**清除DBM的开销**：
```
128GB内存，4KB页：
    33,554,432个页需要清除DBM

但这是必要的：
    - 禁用时一次性开销
    - 保证HDBSS禁用后Guest写内存行为正确
    - 与迁移收益相比可接受
```

### 论点1：Fault发生的频率极低

```
迁移时每个页只会触发一次fault：
    页创建时：RO/无映射 → DBM未设置
    迁移开始：HDBSS启用
    第一次写：fault触发 → 添加DBM → WC状态
    后续写：不再fault → 硬件自动跟踪
```

**每个页在整个迁移期间只会触发一次fault**，这是与生俱来的增量特性。

### 论点2：与"创建时加DBM"相比，防护复杂度大幅降低

| 方案 | 需要防护的路径 |
|------|--------------|
| **迁移fault时加DBM** | `user_mem_abort()` 一处即可 |
| **创建时加DBM** | 所有权限变更路径需防护 |

**动态添加DBM的防护负担**：

| 需要防护的场景 | 说明 |
|---------------|------|
| RO → RW | 需要添加DBM |
| RW → RO | 需要清除DBM |
| RW → Device | 需要清除DBM |
| Huge page拆分 | 需要继承/传递DBM到子页 |
| Page migration | 需要处理DBM状态 |

**实际防护点数量**：至少10+处代码路径

### 论点3：Huge page拆分的复杂性

```
迁移场景下huge page处理：

当前方案（fault时添加DBM）：
    大页 2MB → 拆分后512个小页
    拆分后，访问每个小页时触发fault
    第一次访问：添加DBM
    后续访问：硬件跟踪
    ↓
    实际发生：每个小页只fault一次

替代方案（创建时加DBM）：
    大页 DBM=1 → 拆分成512个小页
    每个小页需要继承DBM=1
    拆分成本：512次操作
    ↓
    128GB内存全是大页：
    33,554,432个小页 × 每次DBM设置 = 巨大的初始化开销
```

**Leo's邮件中的观点**（对huge page的处理）：
> "FEAT_HDBSS speeds up guest memory dirty tracking by avoiding a page fault and saving the entry in a tracking structure. That may be a problem when we have guest memory backed by hugepages or transparent huge pages, as it's not possible to do on-demand hugepage splitting, relying only on eager hugepage splitting."

Leo的方案是启用eager hugepage split，这实际上也是按需拆分（访问时拆分），而非迁移开始时全部拆分。

### 论点4：动态添加DBM的其他代价

```
如果创建时就加DBM：

1. 权限变更路径复杂度：
   - 需要在所有修改页表权限的地方检查DBM状态
   - 需要在kvm_pgtable_stage2_relax_perms等函数中增加DBM逻辑
   - 代码维护成本高，容易遗漏

2. 状态一致性问题：
   - DBM状态需要在多种场景下保持一致
   - 迁移完成后的DBM清理变得复杂

3. 与现有代码耦合：
   - 需要修改多处arch-specific代码
   - HACDBS等后续功能可能受影响
```

### 论点5：当前代码存在 DBM 处理的关键 Bug

**Bug 1：`kvm_pgtable_stage2_pte_prot()` 不提取 DBM**

```c
// pgtable.c:721-736
enum kvm_pgtable_prot kvm_pgtable_stage2_pte_prot(kvm_pte_t pte)
{
    // ...
    if (pte & KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R)
        prot |= KVM_PGTABLE_PROT_R;
    // ... S2AP_W, XN 提取
    // ❌ 没有提取 DBM！
    return prot;
}
```

这导致 Huge Page 拆分时 DBM 丢失。

**Bug 2：`stage2_pte_needs_update` 把 DBM 视为无关位**

```c
// pgtable.c:738-744
static bool stage2_pte_needs_update(kvm_pte_t old, kvm_pte_t new)
{
    if (!kvm_pte_valid(old) || !kvm_pte_valid(new))
        return true;

    return ((old ^ new) & (~KVM_PTE_LEAF_ATTR_S2_PERMS));
    // KVM_PTE_LEAF_ATTR_S2_PERMS 不包含 DBM！
}
```

这导致**清除 DBM 操作被忽略**（如果其他权限不变的话）。

**如果选择"创建时加DBM"方案，这些 bug 必须先修复**：
- 需要修复 `kvm_pgtable_stage2_pte_prot()` 提取 DBM
- 需要修复 `stage2_pte_needs_update` 把 DBM 加入比较

而"Fault时加DBM"方案可以绕过这些 bug（因为拆分后自然fault，fault时加DBM）。

---

## 数据对比

| 指标 | 迁移fault时加DBM | 创建时加DBM |
|------|-----------------|-------------|
| **Fault次数** | 每页1次（增量） | 0次 |
| **防护代码路径** | 1处 | 10+处 |
| **Huge page处理** | 自然拆分 | 需要继承DBM + 修复提取bug |
| **清除DBM需求** | 几乎不需要 | 需要修复stage2_pte_needs_update bug |
| **状态管理复杂度** | 低 | 高 |
| **与现有设计兼容性** | 好 | 需要大量修改 |
| **代码维护成本** | 低 | 高 |
| **Bug修复需求** | 无需修复DBM相关bug | 必须修复2个关键bug |

---

## 结论

**迁移时fault添加DBM的方案是更优选择**：

1. **Fault开销可接受**：每页仅一次，增量特性，整体开销远低于批量添加
2. **防护简单**：只需在一处添加DBM逻辑
3. **Huge page自然支持**：拆分后按需添加DBM，无需额外处理
4. **状态管理简单**：DBM状态仅在HDBSS启用期间维护
5. **代码可维护性高**：不需要在多处权限变更路径上增加DBM逻辑
6. **无需修复现有bug**：当前代码的 DBM 处理 bug 对此方案无影响

**一个page fault的开销远低于维护一个跨所有权限变更路径的DBM状态系统。**

### 创建时加DBM方案需要修复的关键bug

如果选择"创建时加DBM"方案，必须先修复以下bug：

| Bug | 位置 | 问题 |
|-----|------|------|
| `kvm_pgtable_stage2_pte_prot()` | pgtable.c:721-736 | 不提取 DBM，导致拆分时丢失 |
| `stage2_pte_needs_update()` | pgtable.c:738-744 | 把 DBM 视为无关，导致清除操作被忽略 |

### 关于清除 DBM

**结论：几乎不需要清除 DBM**。

原因：
1. **没有非迁移场景的 W→R 路径**：`kvm_pgtable_stage2_wrprotect()` 只在迁移/dirty logging 时调用
2. **迁出端禁用 HDBSS 时不需要清除**：页已迁移走，无意义
3. `stage2_wp_range()` 是迁移清除，**不清除 DBM**（保持脏跟踪）

**核心原则**：变成非可写就清 DBM，迁移清除不动 DBM。

---

## 参考邮件

Leonardo Bras关于HDBSS和Huge page的讨论：
> "FEAT_HDBSS speeds up guest memory dirty tracking by avoiding a page fault and saving the entry in a tracking structure. That may be a problem when we have guest memory backed by hugepages or transparent huge pages, as it's not possible to do on-demand hugepage splitting, relying only on eager hugepage splitting."

这说明当前设计的fault容忍是预期内的，而Leo的eager split补丁也是基于"按需拆分"的思路，而非强制迁移开始时全部拆分。

---

*整理时间：2026-05-08 22:00*
