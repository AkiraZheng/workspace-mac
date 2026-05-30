# 待解决问题清单

本文档记录 merge-patchset skill 已知问题及待改进项。

---

## 问题 1：AI 上下文爆掉后冲掉记忆

### 现象
当 AI 执行多阶段任务（Phase 0 → 1 → 1.5 → 2 → 3）过程中，上下文超过阈值后：
- AI 似乎"忘记"之前的分析内容
- Phase 3 时不生成或漏生成分析报告（analyse.md / summary.md）
- 即使 `$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json` 存在，AI 也可能忽略它

### 根因推测
- LLM 长上下文模型存在"中间遗忘"现象
- 多 Agent 架构中子 Agent 结果未及时落盘到主 Agent 上下文
- Phase 3 执行时，Phase 1/2 的关键信息已不在活跃记忆中

### 可能解决方向

| 方案 | 描述 | 优先级 |
|------|------|-------|
| **强制落盘检查点** | 每阶段结束时，让 AI 输出"已完成 X，关键数据在 Y"的显式确认 | 高 |
| **Phase 3 读取 merge_tasks.json** | Phase 3 开头强制读取 merge_tasks.json，重建上下文 | 高 |
| **分 session 模式** | Phase 3 作为独立 session，启动时读取缓存文件重建状态 | 中 |
| **summary.md 模板简化** | 减少 Phase 3 需要从记忆提取的内容量 | 中 |

### 关联改动
- 已在 Phase 3 末尾加硬编码提醒（检查文件是否生成）
- 需要在 Phase 3 开头加"读取 merge_tasks.json 重建上下文"步骤

---

## 问题 2：GLM5 不按规则执行编译验证（急急急）（已修改，待验证）

### 现象
GLM5 模型在执行 Phase 2 merge 流程时：
- **跳过 BUILD 步骤**：直接从 APPLY → COMMIT，不执行编译
- **不完整编译**：只编译部分中间产物（如 `.o` 文件），不验证最终产物（如 `Image`）
- **忽视错误**：编译有 error/warning 时仍然继续 commit

### 硬性约束原文（SKILL.md）
> 5. **每 patch 必须编译验证**：执行 `$BUILD_CMD`，0 error + 产物存在

### 根因推测
- GLM5 对"编译通过"的定义理解不准确
- 模型倾向于"捷径思维"，认为部分成功即成功
- BUILD 步骤的"通过条件"描述不够严格

### 可能解决方向

| 方案 | 描述 | 优先级 |
|------|------|-------|
| **BUILD 步骤加硬性校验脚本** | 编译后执行校验脚本，检查 error 数 + 产物存在 | 高 |
| **BUILD 步骤加显式输出模板** | 强制 AI 输出"编译命令: X，error 数: 0，产物: Image 存在" | 高 |
| **BUILD 步骤失败则阻塞** | 编译失败时禁止进入 COMMIT，必须停在 BUILD | 高 |
| **修改 SKILL.md BUILD 章节（已改为整个仓库编译强制约束）** | 强制整个仓库编译 + error=0 + 产物存在 + 显式输出 | 中 | ✅ SKILL.md 已更新，强制约束落地 |

### 建议修复内容
在 SKILL.md Phase 2 BUILD 步骤中：

**改为**：
```
### BUILD
执行完整编译，**不允许跳过或只编译部分产物**。

$BUILD_CMD -j$(nproc)

**通过条件（必须同时满足）**：
1. error 数 = 0（检查编译输出中的 error 计数）
2. 最终产物存在（如 `arch/arm64/boot/Image`）

**不通过时**：
- 禁止进入 COMMIT 步骤
- 分析错误原因，最小修改修复
- 重新执行 BUILD 直到通过

**显式输出要求**：
[BUILD 检查]
编译命令: make ARCH=arm64 Image -j8
error 数: <从编译输出提取>
最终产物: <ls 检查结果>
结果: 通过/不通过
```

---

## 问题 3：没有执行 review skill（不急，先把基础能力调通）

### 现象
Phase 2 COMMIT 后应调用 code-review-expert skill 做 review，但常被跳过。

### 可能原因
- 模型忘记 review 步骤
- 上下文不足，无法加载 review skill

### 状态
🟡 待处理，优先级 P2

---

## 问题 4：diff 输出内容不清晰（✅ 已修复，待验证）

### 问题
原来输出完整的原始 patch + 完整 git show，内容冗长，用户想知道"到底偏离了什么"。

### 修复
- `generate_diff_report.py` 重写：只输出差异对比段落
- 参数改为 `--source patch:<path>` 或 `--source commit:<hash>`（支持 revert 场景）
- `output-templates.md` 第 9 章更新为差异对比定义

---

## 问题优先级排序

| 优先级 | 问题 | 影响 | 状态 |
|-------|------|------|------|
| P0 | GLM5 不执行完整编译 | patch 编译失败，功能不可用 | 🔴 SKILL.md BUILD 已强化，待验证 |
| P1 | AI 上下文爆掉忘记生成报告 | 分析数据丢失 | 🔴 已加 Phase 3 提醒，待观察 |
| P2 | 没有执行 review skill | 代码质量无保障 | 🟡 待处理 |
| P3 | diff 输出不清晰 | 用户看不清变化 | ✅ 已加，待观察 |
