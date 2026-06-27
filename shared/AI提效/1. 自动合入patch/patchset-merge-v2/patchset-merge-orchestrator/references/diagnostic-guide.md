# 诊断指南 — 索引

> **注意**：本文件已拆分为 Layer 3 的专属 references。

## 冲突决策树 → `layer3-execution/references/conflict_decision_tree.md`

包含：
- Ours vs Theirs 决策表（10 个场景）
- APPLY 降级链（`--3way` → `--reject` → 手工匹配）
- 最小化修改原则
- 编译修复分类
- APPLY 后意图校验流程（`verify_patch_intent.py` 退出码和校验流程）

## 编译修复 → `layer3-execution/references/build_fix_strategy.md`

包含：
- 硬性约束（禁止 git reset --hard 等）
- 根因定位三重匹配
- rebase amend 修复流程
- 手工文件保护规则

## 执行状态机 → `layer3-execution/references/execution_state_machine.md`

包含：
- 7 步状态机定义（PRECHECK → DONE）
- gatekeeper.py 用法和动态前置依赖
- PRE_REVERT 特殊逻辑
