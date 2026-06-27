# 降级机制指南

当脚本执行失败或超时时的降级处理策略。

## 降级原则

1. **优先 AI 手工处理**：脚本失败后，AI 用 Bash/Read 工具直接操作，不依赖脚本
2. **保留失败现场**：记录失败原因和上下文，供后续恢复
3. **不丢失上游数据**：即使降级，patch 文件、分析结果等核心数据必须落盘

## 降级场景

### 1. download_patches.py 失败

- **b4 超时**（>2min）：降级为 wget 从 lore.kernel.org 直接下载原始 patch
- **URL 不可达**：提示用户提供本地 patch 路径
- **本地路径不存在**：提示用户确认路径

### 2. detect_duplicate_sample.py 失败

- 降级：AI 直接读取每个 patch 的前 30 行，提取涉改文件和符号名，用 `grep -F` 在目标仓库对应文件中搜索
- 这是快操作（<2s），通常不需要降级

### 3. extract_patch_symbols.py 失败

- 降级：AI 直接读取每个 patch 文件，解析 `Subject:` 行和 `diff --git` 行提取符号
- 执行时间 <3s，通常不需要降级

### 4. calculate_build_checkpoints.py 失败

- 降级：AI 按 7 条规则手工计算每个 patch 的 build_checkpoint：
  1. Rule 1a: 反向依赖者 → false
  2. Rule 1b: 反向依赖的被依赖者 → true
  3. Rule 1: infra patch → true
  4. Rule 2: symbols 被 ≥3 个 later patches 引用 → true
  5. Rule 3: risk_level='高' 或 conflicts_predicted 非空 → true
  6. Rule 4: 最后一个 patch → true
  7. Rule 5: doc patch → false
  8. Rule 6: 功能模块分组最后一个 → true
  9. Rule 7: 其他 → false

### 5. gatekeeper.py 失败

- 降级：AI 直接读写 merge_tasks.json 更新状态字段
- 门禁逻辑用 Read 工具检查 state_log 数组手动判断

### 6. verify_patch_intent.py 失败

- 降级：AI 读取 patch 文件和 git diff，手动对比 `+` 行和 introduced_symbols 是否存在

### 7. generate_analyse_md.py 失败

- 降级：AI 读取 analyse_template.md 模板，手动填充执行日志

### 8. generate_summary_md.py 失败

- 降级：AI 读取所有 analyse.md，按 summary_template.md 模板手工汇总

## JSON 格式校验失败

- gate_check.sh 校验 JSON 失败时，AI 手工检查并修复
- 若无法修复：标记该文件为异常，写入 state.json 记录失败原因
- 后续恢复时跳过已标记异常的文件

## Subagent 超时

- agent_target_revert 超时：降级为 AI 在主 Agent 中直接执行 git log --grep 搜索
- agent_upstream_deps 超时：跳过上游依赖搜索，标记为 unknown，后续 patch 应用时如果遇到缺失符号再补充
