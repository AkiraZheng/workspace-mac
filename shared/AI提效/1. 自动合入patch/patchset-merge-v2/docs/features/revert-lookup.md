# Revert 查找规则设计

## 当前缺口

Phase 1 分析 Agent 产出的 `revert` 字段（例如 `revert=建议 | abc123`）没有定义是如何找到 `abc123` 这个 commit 的。需要补一个在目标仓库上查找本地冲突实现的步骤。

## 在 Phase 1 中的位置

在步骤 5（检测目标仓库重复 patch）之后、步骤 6（屏幕输出）之前：

```
步骤 3: 向后搜索 Bugfix         → upstream git blame / Fixes 标签
步骤 4: 向前搜索依赖             → upstream git log -S
步骤 5: 检测目标仓库重复 patch    → 目标仓库 git log --grep/-S/-L
步骤 6: [本步骤] 查找需 revert 的本地实现 → 目标仓库 git log -S
步骤 7: 屏幕输出
```

## 查找命令

在目标仓库上执行：

```bash
# 对 patch 中每个 引入/修改的函数名，在目标仓库查找本地修改历史
git -C "$KERNEL_REPO_PATH" log --all --oneline -S "<function_name>"

# 过滤：排除 upstream commit（通过 git branch --contains 检查）
# 仅保留 非 upstream 的本地 commit
```

## 判定标准

| 情况 | 判定 | revert 等级 |
|------|------|------------|
| 本地实现了 patch 的同等功能（独立特性实现，修改同一函数，逻辑重复） | 合入后两套实现并存导致逻辑冲突 | **必须** |
| 本地修改了 patch 要改的同一区域，且 commit 非 upstream 来源 | 大概率合并冲突 | **建议** |
| 本地修改了同一文件但不同函数 / 无关 bugfix | 合入时需注意，但不需回退 | **无须**（记录冲突预警） |
| 目标仓库无任何 commit 修改该函数 | 无冲突 | **无须** |

## 与现有步骤的关系

| 步骤 | 仓库 | 找什么 | 用途 |
|------|------|--------|------|
| 步骤 3 向后搜索 | upstream | 上游修复了本 patch 引入的 bug | bugfix 依赖 |
| 步骤 4 向前搜索 | upstream | 本 patch 缺失的前置 commit | 高版本依赖 |
| 步骤 5 重复检测 | 目标仓库 | 已有等效 patch 已合入 | 避免重复合入 |
| ★ 本步骤 | 目标仓库 | 本地有冲突实现需要回退 | revert 判定 |

四步覆盖 上游依赖 → 上游 bugfix → 目标重复 → 目标冲突，完整依赖/冲突发现链。

## 输出

在屏幕输出格式中 `revert` 字段的值：

```
# 有需要 revert 的
revert=必须 | abc123,def456
revert理由=本地独立实现了 kvm_stage2_get_level 函数，与 patch 冲突

# 有建议 revert 的
revert=建议 | abc123
revert理由=本地修改了同一区域的页表遍历逻辑

# 无需要 revert 的
revert=无须
revert理由=目标仓库无本地冲突实现
```

## 后续接入

此功能作为草稿保存在 `features/` 目录。接入时需修改：
- `SKILL.md`：Phase 1 新增步骤 6（现步骤 6→步骤 7）
- `output-templates.md`：revert 字段示例更新
