# 冲突诊断决策树指南

## 总则

当 `git am --3way` 失败时，按降级链处理：`--3way` → `--reject` → 手工 hunk 匹配。对每个冲突，按以下决策树选择 ours 或 theirs。

## Ours vs Theirs 决策表

| 场景 | Ours（目标仓库代码） | Theirs（patch 代码） | 抉择 | 理由 |
|------|---------------------|---------------------|------|------|
| **patch 的 `+` 行（新增代码）** | 无对应代码或有冲突 | patch 新增内容 | **Theirs（强制保留）** | 这是 patch 的核心意图，不可丢失 |
| **patch 引入的关键符号（introduced_symbols）所在行** | 上下文冲突 | patch 定义的新函数/宏 | **Theirs（强制保留）** | 核心符号定义不可删，否则 patch 功能缺失 |
| 上下文行差异 | 目标仓库真实上下文 | patch 中的上下文行 | **Ours** | 上下文是定位锚点，目标仓库代码是真实代码 |
| 独立新功能（新增函数/宏/类型） | 无对应代码 | 新增内容 | **Theirs** | 全量接受新功能 |
| 上游重构 vs 本地 | 上游版本的同函数 | 上游新版本的重构 | **Theirs** | 上游版本更新且权威 |
| 上游重构 vs 下游特有补丁 | 下游特有补丁 | 上游重构 | **人工裁定** | 下游特有修改不可丢弃 |
| 同 bug 不同修复 | 目标仓库本地修复 | 上游修复 | **Theirs** | 上游修复更权威 |
| 新功能 vs 本地 hack | 本地临时方案 | 上游正式实现 | **建议 Theirs** | 记录本地历史供评估 |
| 独立本地特性 | 目标仓库独有实现 | 无关上游改动 | **Revert ours → Theirs** | 先回退本地特性，合入后叠加 |
| 无法自动判定 | — | — | **暂停** | 输出 ours vs theirs 代码对比给用户裁定 |

## APPLY 降级链

```
git am --3way <patch>
  ├─ 成功 → 进入 BUILD
  └─ 失败 → git apply --3way --reject
       ├─ 成功 → 分析 .rej 文件，按决策表手动填入
       └─ 失败 → 读取 .patch 文件，逐 hunk 手工匹配
```

## 最小化修改原则

1. 只改冲突区域的代码，同行文件其他部分不动
2. 保持目标仓库代码风格（缩进、命名、注释）
3. 编译通过是验证标准
4. 不改 Makefile/Kconfig，不碰 .config 逻辑

## 编译修复分类

| 错误类型 | 处理方式 |
|---------|---------|
| patch 代码本身的语法/逻辑错误 | 编辑源文件最小修复 |
| 调用不存在的符号 | 标记为缺失依赖，尝试最小适配或 stub |
| 非 patch 的 config 问题 | 临时改 .config → make → git restore .config，记录在 analyse.md |

## APPLY 后意图校验

**每次 APPLY（含冲突解决）完成后，必须执行校验**：

```bash
python3 "$SCRIPTS_DIR/verify_patch_intent.py" \
  --patch-file <patch_path> \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id <task_id> \
  --repo-path "$KERNEL_REPO_PATH"
```

**退出码**：

| 退出码 | 含义 | 处理 |
|--------|------|------|
| 0 | patch 意图完整保留 | 进入 BUILD |
| 1 | 部分 + 行缺失 | 检查缺失行 → 手动补充 → 重新校验 |
| 2 | 参数错误 | 检查文件路径 |
| 3 | introduced_symbols 缺失 | **严重：核心功能代码丢失，暂停等待用户决策** |

**校验流程**：
```
APPLY（含冲突解决）
    │
    ▼
verify_patch_intent.py
    │
    ├─ 0: → BUILD
    ├─ 1: → 补充缺失行 → 重新校验
    └─ 3: → 暂停，输出缺失符号列表 → 用户决策
```

**自检清单**（AI 在 APPLY 后应确认）：
1. 冲突解决后，patch 的 `+` 行是否全部保留（不可选 Ours 删除）
2. introduced_symbols 是否存在于工作区文件中
3. 若为手动填入 .rej 内容，是否完整无遗漏
