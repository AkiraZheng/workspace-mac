# 输出模板参考

需要向用户输出或写入文件时，按此模板。分三种输出类型：

- **对话输出**（Markdown 块）→ 直接展示给用户，简洁可扫读
- **分析文档**（写入 `.patchset-analysis/` 目录）→ 每个 patch 的逐行 diff 对比和冲突解决过程
- **汇总报告**（写入 `.patchset-summary.md`）→ 合入报告 + 风险评级总结（合并为一个文件）

---

## 相位 0 输出：前置检测结果

Agent 全部返回后，用此模板汇总。在 Phase 0 结束时输出。

```markdown
## 🔍 前置检测结果

### 冲突预检
| # | Patch 标题 | 风险 | 依据 |
|---|-----------|------|------|
| 1 | <title>   | HIGH | <具体原因，如：函数 foo_init 在目标仓库已存在> |
| 2 | <title>   | LOW  | <原因> |
| 3 | <title>   | NONE | <原因> |

### 依赖检测
> 仅在指定 --upstream 时展示

| # | Upstream Commit | 标题 | 分级 | 匹配理由 | 推荐操作 |
|---|-----------------|------|------|---------|---------|
| 1 | abc123          | <title> | 强功能 | patch 多处使用依赖引入的宏 KVM_PGTABLE_LAST_LEVEL | 拉取 |
| 2 | def456          | <title> | 弱上下文 | 仅需函数骨架，依赖引入的功能与本次合入无关 | 手工创建 stub |

- **强功能依赖**：不拉取无法编译，拉取代价可接受 → 拉取
- **弱上下文依赖**：可通过修改 patch 上下文或创建最小 stub 解决 → 不拉取，用冲突解决替代

未找到依赖时显示: `未发现缺失的依赖 commit`

### 相似度检测与 Revert 定位

| # | Patch | 相似度 | 匹配文件 | 引入 Commit | Commit 标题 | 依赖链 | Revert 安全 | 依据 |
|---|-------|--------|---------|-------------|------------|--------|------------|------|
| 1 | <title> | 高 | drivers/foo.c | abc123 | "add: foo driver" | 无 | ✅ 可 revert | 后续无 commit 依赖 foo_init |
| 2 | <title> | 高 | kernel/bar.c | def456 | "add: bar core" | ghi789, jkl012 | ⚠ 高危 | 需一并 revert ghi789 和 jkl012 |
| 3 | <title> | 中 | mm/alloc.c | mno345 | "refactor: alloc" | pqr - vwx - bcd | 🔴 不可 revert | 3 层依赖链，代价过大 |

> **Revert 安全**: ✅ 可 revert / ⚠ 高危需链式 revert / 🔴 不可 revert（退回冲突解决）
> 相似度"低"的 patch 不需要 revert，走正常的冲突解决流程即可。
未找到相似代码时显示: `目标仓库中未发现相似代码，无需 revert`
```

---

## 相位 1 输出：场景判定 + 执行计划

在 Phase 1 结束时输出，**必须等用户确认后才进入 Phase 2**。

```markdown
## 📋 场景判定

- **场景**: <A / B / C / E，可组合如 B + C>
- **判定依据**:
  - <场景 X>: <触发条件，如 patch #1 冲突风险 HIGH，Agent C 找到相似 commit abc123>
  - <场景 Y>: <触发条件，如 patch #2 缺失依赖，Agent B 分级为强功能依赖>

### 执行计划
| 步骤 | 操作 | 详情 |
|------|------|------|
| 1 | 创建分支 | patch-<keyword> |
| 2 | Revert 旧 commit | 逆序 revert N 个 commit（场景 B，由 Agent C 定位） |
| 3 | 拉取强依赖 | 从上游拉取 N 个强依赖 patch（场景 C） |
| 4 | 路径适配 | 调整 N 个 patch 中的文件路径（场景 E） |
| 5 | Merge | 合入 N 个 patch |
| 6 | 编译验证 | 每个 patch 后编译 |
| 7 | 生成报告 | .patchset-summary.md |

### 依赖处理策略（场景 C 时展示）
| # | 依赖 Commit | 分级 | 处理方式 | 理由 |
|---|------------|------|---------|------|
| 1 | abc123 | 强功能 | 拉取 | patch 0005 5 处使用其定义的宏，手工替代代价高 |
| 2 | def456 | 弱上下文 | 手工创建 stub | 仅需函数骨架，拉取完整 commit 会引入不相关的 idregs 代码和结构性冲突 |

> 弱依赖不拉取，在 Phase 2 通过创建最小化 stub / 调整 patch 上下文解决。

确认以上计划后开始执行。
```

---

## 相位 2 输出：前置操作进度

每个前置操作输出一行进度 + 结果。

**场景 B — Revert**：
```
## ⏪ Revert 旧代码 (1/3)
- Commit: abc123 "fix: hdbss init"
- 策略: git revert --no-edit ✓
- Revert Commit: def456
```

**场景 C — 拉取依赖**：
```
## 📥 拉取依赖 patch (1/2)
- Upstream Commit: abc123 "add: bar_setup helper"
- 已生成: /tmp/deps-patches/0001-add-bar_setup-helper.patch
```

**场景 E — 路径适配**：
```
## 🔀 路径适配
| 原始路径 | 目标路径 |
|---------|---------|
| drivers/net/hdbss.c | drivers/net/ethernet/vendor/hdbss.c |
| include/linux/hdbss.h | include/linux/hdbss.h (不变) |
```

---

## 相位 3 输出：Merge 进度

### 3.3 解析完成后输出 patch 清单

```markdown
## 📝 待合入 patch 清单
| # | 文件 | 标题 | 涉及文件数 |
|---|------|------|-----------|
| 1 | 0001-xxx.patch | <title> | 3 |
| 2 | 0002-yyy.patch | <title> | 1 |
| 3 | 0003-zzz.patch | <title> | 2 |

共 N 个 patch，开始逐个合入。
```

### 3.5 每个 patch 合入后输出进度

```markdown
## 📝 Patch (N/M)
- **标题**: <subject>
- **策略**: git am ✓（或：解冲突 ✓ / git apply --3way ✓ / git apply ✓）
- **Commit**: <hash>
- **编译**: ✓ 通过（或：✗ 失败，见下方错误）
```

失败时追加错误详情：
```
- **错误**: 
  ```
  <编译错误前 5 行>
  ```
- **状态**: ⚠ 等待用户决策
```

### 3.7 全部完成后对话输出总结

```markdown
## ✅ 合入完成

| 项目 | 值 |
|------|-----|
| 分支 | <branch> (已保留) |
| 场景 | <A / B / C / E 组合> |
| 合入 | N 成功 / K 失败 |
| Revert | N 个旧 commit（如有） |
| 依赖 | N 个拉取的依赖（如有） |
| 报告 | <source_dir>/.patchset-summary.md |

### 失败详情（如有）
| # | Patch | 失败原因 |
|---|-------|---------|
| 3 | xxx   | 全部策略失败，冲突文件: a.c, b.h |
```

---

## 文件输出：`.patchset-summary.md`

写入源码目录，保留完整记录（合入报告 + 风险评级总结合并在一个文件中）。用 Write 工具生成。

```markdown
# Patchset 合入报告

## 概要
- **日期**: <YYYY-MM-DD HH:MM>
- **场景**: <A / B / C / E 组合>
- **分支**: <branch> (已保留)
- **目标仓库**: <source_dir>
- **上游仓库**: <upstream_dir>（如有）
- **总数**: N / **成功**: N / **失败**: N
- **Revert 的旧 commit**: N 个
- **拉取的依赖 patch**: N 个

## 前置检测摘要
### 冲突预检
| # | Patch | 风险 | 依据 |
|---|-------|------|------|
...

### 依赖检测
...

### 相似度检测与 Revert 定位
| # | Patch | 相似度 | 引入 Commit | Commit 标题 | 依赖链 | Revert 安全 | 依据 |
|---|-------|--------|-------------|------------|--------|------------|------|
...

## 前置操作
### Revert（如有）
| # | 原始 Commit | 标题 | Revert Commit |
|---|-------------|------|---------------|
| 1 | abc123      | xxx  | def456        |

### 拉取的依赖（如有）
| # | Upstream Commit | 标题 | 本地 Patch 文件 |
|---|-----------------|------|-----------------|
| 1 | abc123          | xxx  | /tmp/deps-patches/0001-xxx.patch |

## 各 patch 合入状态
| # | Patch 文件 | 标题 | 状态 | 策略 | Commit |
|---|-----------|------|------|------|--------|
| 1 | 0001-xxx.patch | <title> | ✓ 成功 | git am | abc123 |
| 2 | 0002-yyy.patch | <title> | ✗ 失败 | — | — |

## 关键冲突解决记录
### <patch>: <冲突简述>
- <具体解决过程>

## 编译状态
- **状态**: ✓ 全部通过 / ⚠ 无法验证 / ✗ 失败
- **说明**: <详细说明>

## 风险评级总结

### 整体评估

| 项 | 值 |
|----|-----|
| 整体风险等级 | 🟢 LOW / 🟡 MEDIUM / 🟠 HIGH / 🔴 CRITICAL |
| 总 patch 数 | N |
| CRITICAL | N |
| HIGH | N |
| MEDIUM | N |
| LOW | N |

### 风险热力图

| # | Patch | 风险 | 差异行数 | 合入策略 | 涉及子系统 | 需关注点 |
|---|-------|------|---------|---------|-----------|---------|
| 1 | <title> | 🟢 LOW | 0/45 | ① git am | net/core | — |
| 2 | <title> | 🟠 HIGH | 12/67 | ⑦ 手解冲突 | drivers/hdbss | 函数签名变更 |
| 3 | <title> | 🟡 MEDIUM | 3/30 | ⑤ git apply --3way | fs/ext4 | 上下文偏移 |

### 需重点关注的 patch

> 仅列出 HIGH 和 CRITICAL 级别的 patch

### patch #2: <title> (🟠 HIGH)
- **差异原因**: 目标仓库中 `hdbss_init()` 多了一个 `flags` 参数
- **潜在风险**: 如果未来上游 patch 修改同一函数，需要再次适配
- **建议**: 合入后人工 review `drivers/hdbss/core.c` 的合入结果

### 各 patch 分析文档

| # | Patch | 分析文档 |
|---|-------|---------|
| 1 | <title> | [analysis](./.patchset-analysis/0001-<slug>-analysis.md) |
| 2 | <title> | [analysis](./.patchset-analysis/0002-<slug>-analysis.md) |

## 失败详情（如有）
### patch #3: <title>
- **失败原因**: <原因>
- **尝试的策略**: git am → git apply --3way → git apply → git commit
- **冲突文件**:
  - drivers/net/example.c
- **错误信息**:
  ```
  <具体错误>
  ```
```

---

## Per-patch 分析文档

每个 patch 合入成功后立即生成，写入 `<source_dir>/.patchset-analysis/<序号>-<slug>-analysis.md`。

首先生成 `mkdir -p <source_dir>/patchset-analysis`。

**核心要求**：必须包含源 patch 与实际合入 commit 之间的 diff 对比。用 `git diff` 生成：

```bash
# 获取原始 patch 和实际 commit 之间的差异
diff <(git -C <source_dir> show <commit_hash> --format=raw) <(cat <original_patch_file>) || true
```

模板：

```markdown
# Patch 分析: <patch subject>

## 基本信息
| 项 | 值 |
|----|-----|
| 原始 patch 文件 | <filename> |
| 合入 commit | <hash> |
| 合入策略 | ① git am / ② git am --3way / ③ git am --ignore-whitespace / ④ patch --fuzz / ⑤ git apply --3way / ⑥ git apply --reject / ⑦ 手解冲突 / ⑧ git apply |
| 涉及文件 | N 个 |
| 编译结果 | ✓ 通过 (1次) / ✓ 通过 (修复 N 次) / ✗ 失败 |
| 分析时间 | <YYYY-MM-DD HH:MM> |

## 编译修复记录

> 如果编译一次通过则写 "编译一次通过，无修复"。如果经历过 fix loop 则每轮记录。

| 轮次 | 错误类型 | 错误摘要 | 修复方式 | 结果 |
|------|---------|---------|---------|------|
| 1 | 未声明的函数 | `implicit declaration of function 'hdbss_get_flags'` | 在 `core.c` 添加 `#include "hdbss.h"` | 仍失败 |
| 2 | 类型不匹配 | `expected 'struct hdbss_ctx *' but argument is of type 'void *'` | 在调用处添加 `(struct hdbss_ctx *)` cast | ✓ 通过 |

## 源 patch vs 实际合入 diff

> 以下 diff 展示原始 patch（a/）与最终合入到仓库的代码（b/）之间的差异。
> 标记 `!` 的行代表合入时被修改的内容。

### 文件: <filepath>

```diff
--- a/<filepath> (原始 patch 意图)
+++ b/<filepath> (实际合入结果)
@@ -<line>,<n> +<line>,<n> @@
  <unchanged context>
- <原始 patch 中要删除的行>
+ <原始 patch 中要添加的行>
! <合入时被修改的行 — 与原始 patch 不同>
```

> 对每个涉及文件重复 ### 块。

## 逐行差异明细

对每一处合入时产生的差异，列出原因：

| 行号 | 原始 patch 内容 | 实际合入内容 | 差异原因 |
|------|----------------|-------------|---------|
| 42   | `foo(x)`       | `foo(x, y)` | 目标仓库中 `foo` 签名已变更，合入时适配了新签名 |
| 87   | `return 0;`    | `return ret;` | 冲突解决：目标仓库要求返回错误码 |
| —    | （不存在）       | `#include "compat.h"` | 冲突解决时新增的依赖头文件 |

> 无差异则写 "合入内容与原始 patch 完全一致，无逐行差异。"

## 冲突解决过程

> 如果使用了 git am 直接成功且无差异，写 "未发生冲突，git am 直接合入成功。"

- **冲突文件**: <列出有冲突的文件，无则写"无">
- **冲突类型**: <函数签名不匹配 / 上下文行偏移 / 变量名冲突 / 新增代码冲突 / 无>
- **解决策略**: <描述具体如何解决的>

### 思考过程

```
<记录冲突解决时的分析思路：
- 为什么选择这种解决方式？
- 放弃了哪些替代方案？为什么？
- 目标仓库中哪些已有代码影响了决策？
- 是否有需要注意的隐患？>
```

## 风险评级

| 项 | 评估 |
|----|------|
| **风险等级** | 🟢 LOW / 🟡 MEDIUM / 🟠 HIGH / 🔴 CRITICAL |
| **差异程度** | N 行不同 / 总共 M 行（N/M = X%） |
| **合入策略** | git am / 冲突解决 / git apply --3way / git apply |
| **涉及子系统** | <kernel core / 驱动 / 文件系统 / 网络 / 架构相关 / ...> |
| **判定依据** | <根据风险评级标准逐条说明> |

## 附录

> 原始 patch 文件与合入后实际 commit 之间的 diff 对比。

生成方式：

```bash
# 提取原始 patch 中的纯 diff 部分（去掉邮件头），与合入后 commit 的 diff 做对比
git -C <source_dir> show <commit_hash> --format="" > /tmp/actual_commit.diff
diff <original_patch_file> /tmp/actual_commit.diff > /tmp/patch-vs-commit.diff 2>&1 || true
```

输出格式：

```diff
--- a/<original_patch_file>  (原始 patch)
+++ b/<commit_hash>         (合入后 commit)
@@ -<line>,<n> +<line>,<n> @@
 <原始 patch 中存在的行，合入后 commit 中不存在 / 被修改>
 <合入后 commit 中新增的行，原始 patch 中不存在>
```

> 如果完全一致，则写 "原始 patch 与合入后 commit 完全一致，无差异。"

> 附录 diff 由脚本自动生成，保留完整输出，不截断。
```

---

## 风险评级标准

对每个 patch 按以下标准评级：

### 🔴 CRITICAL — 必须人工 review
触发任一条件：
- 合入后编译失败
- 冲突解决时**删除了目标仓库已有的代码**（非 patch 意图删除的行）
- 修改了核心数据结构定义（`struct`、`union`、`enum` 的成员变更）
- 修改了导出函数签名（`EXPORT_SYMBOL` 的函数参数或返回值变更）
- 涉及安全相关代码（权限检查、内存屏障、加密）

### 🟠 HIGH — 建议人工 review
触发任一条件：
- 使用了冲突解决（策略②），实际合入与源 patch 差异 ≥ 10 行
- 差异行数超过 patch 总行数的 20%
- 涉及 Kconfig / Makefile / CMakeLists.txt 变更
- 涉及多个子系统的交叉修改
- 涉及设备树（.dts / .dtsi）变更

### 🟡 MEDIUM — 注意但不阻塞
触发任一条件：
- 使用了 `git apply --3way`（策略③）而非 `git am`
- 差异行数在 5%~20% 之间
- 涉及设备驱动代码（`drivers/`）
- 上下文行偏移超过 10 行

### 🟢 LOW — 可直接合入
满足全部条件：
- `git am` 直接成功（策略①）
- 实际合入内容与源 patch 完全一致（0 行差异）
- 编译通过
- 不涉及核心数据结构或安全代码

---

## 输出规则

1. **每个相位的输出必须在进入下一相位前完成**，不得省略
2. **相位 1 场景判定**输出后必须等待用户确认，不得自动继续；相位 3 中的冲突解决和编译修复由 AI 自行分析决策，不需人工介入
3. **进度输出使用 N/M 格式**，让用户清楚知道当前进度
4. **所有表格必须用 Markdown 表格**，不得用纯文本罗列
5. **三种输出职责分离**：
   - 对话输出：给用户即时看，简洁可扫读
   - 分析文档（`.patchset-analysis/`）：每个 patch 的逐行 diff 对比和思考过程，供事后审计
   - 汇总报告（`.patchset-summary.md`）：合入报告 + 风险评级总结（合并为一个文件）
6. **状态图标统一**：✓ 成功 / ✗ 失败 / ⊘ 跳过 / ⚠ 等待决策 / — 不适用
7. **风险图标统一**：🟢 LOW / 🟡 MEDIUM / 🟠 HIGH / 🔴 CRITICAL
8. **每个 patch 合入后立即生成分析文档**，不得等到全部合入后再补（防止遗忘冲突解决细节）
9. **源 patch vs 实际合入的 diff 必须逐文件展示**，不得省略或概括
10. **思考过程必须用自然语言记录**分析时的判断依据，不得留空或写"无"
