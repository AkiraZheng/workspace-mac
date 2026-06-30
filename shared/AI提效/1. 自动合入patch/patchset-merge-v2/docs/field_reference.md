# 字段参考手册

> 本文档仅供人类维护者查阅各 JSON schema 字段的生产者和消费者关系。
> AI 执行时不会加载此文件。

---

## config.json（Layer 1 产出）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `schema_version` | Layer 1 | gate_check.sh | 接口版本校验 |
| `patch_source` | Layer 1 解析用户输入 | Layer 2 下载 patch | message-id / URL / 本地路径 |
| `kernel_repo_path` | Layer 1 | Layer 2,3,4 | 目标仓库绝对路径 |
| `kernel_branch` | Layer 1 自动创建 | Layer 2,3 | 操作分支名（工作分支） |
| `baseline_branch` | Layer 1 自动检测 | Layer 4 format-patch | 基线分支，format-patch 用 |
| `kernel_arch` | Layer 1 从 .config 提取 | Layer 3 BUILD | 固定 arm64 |
| `build_cmd` | Layer 1 构造 | Layer 3 BUILD | 编译命令 |
| `upstream_repo_path` | Layer 1 | Layer 2 Subagent | 上游仓库路径，可选 |
| `output_dir` | Layer 1 构造 | Layer 2,3,4 | 所有输出文件的根目录 |
| `scene` | Layer 2 用户选择后回写 | Layer 2,3 | upgrade / backport |
| `user_input_original` | Layer 1 | Layer 2 调试 | 用户原始输入，仅追溯用 |
| `extracted_at` | Layer 1 | 无 | 时间戳，仅记录 |

---

## merge_tasks.json（Layer 2 产出，Layer 3/4 消费）

### 顶层字段

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `schema_version` | Layer 2 | gate_check.sh | 接口版本校验 |
| `patchset_info` | Layer 2 | Layer 3,4 | 来源/目标基本信息 |
| `workflow_hints` | gatekeeper.py | Layer 3 | 关键流程提示 |
| `current_state` | gatekeeper.py | Layer 3 恢复 | 当前执行状态 |
| `global_revert_order` | Layer 2 Subagent | Layer 3 Phase 1 | revert 执行顺序 |
| `deps_order` | Layer 2 Subagent | Layer 3 Phase 2 | 上游依赖列表 |
| `merge_order` | Layer 2 | Layer 3 Phase 3 | 主体合入任务列表 |

### merge_order / deps_order 任务字段

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `seq` | Layer 2 AI | **Layer 3 强依赖** | 执行序号，Layer 3 严格按此升序执行 |
| `task_id` | Layer 2 AI | Layer 3,4 gatekeeper | patch 标识（如 0001 / dep-001） |
| `patch_file` | Layer 2 | **Layer 3 强依赖** | git am 的输入文件绝对路径 |
| `action` | Layer 2 AI | **Layer 3 强依赖** | apply（合入）或 skip（跳过） |
| `pre_revert` | Layer 2 Subagent | **Layer 3 强依赖** | 需先 revert 的 commit hash 列表 |
| `depends_on` | Layer 2 AI | **Layer 3 强依赖** | 前置 task_id 列表 |
| `build_checkpoint` | Layer 2 脚本 | **Layer 3 强依赖** | 是否在此点做编译验证 |
| `checkpoint_reason` | Layer 2 脚本 | Layer 2 展示 | checkpoint 判定依据和责任规则 |
| `status` | Layer 3 gatekeeper | Layer 3,4 | 运行时状态（pending/in_progress/done/blocked/skipped/failed） |
| `state_log` | Layer 3 gatekeeper | Layer 3,4 | 7 步状态机记录（step/time/result/error_count/...) |
| `execution_log` | Layer 3 | Layer 4 | 冲突和编译修复详情 |
| `功能分类` | Layer 2 脚本 | Layer 2 展示 | infra/core/driver/fs/net/sound/doc/bugfix |
| `introduced_symbols` | Layer 2 脚本 | Layer 2 展示 | 本 patch 新增/修改的符号 |
| `referenced_symbols` | Layer 2 脚本 | Layer 2 展示 | 本 patch 引用/调用的符号 |
| `subject` | Layer 2 AI | Layer 4 展示 | patch 标题（Layer 3 不读） |
| `author` | Layer 2 AI | Layer 2 展示 | patch 作者（Layer 3 不读） |
| `files_changed` | Layer 2 AI | Layer 2 展示 | 涉改文件列表（Layer 3 不读） |
| `risk_level` | Layer 2 AI | Layer 2 展示 | 高/中/低（仅用户确认界面） |
| `review_required` | Layer 2 AI | Layer 2 展示 | 高/中/低（仅用户确认界面） |
| `blame_hits` | Layer 2 AI | Layer 2 展示 | git blame 追溯的 bugfix commit（仅展示） |
| `duplicate_info` | Layer 2 AI | Layer 2 展示 | 重复 patch 检测结果（仅展示） |
| `conflicts_predicted` | Layer 2 AI | Layer 2 展示 | 预判冲突点（仅展示） |
| `special_notes` | Layer 2 AI | Layer 2 展示 | 合入注意事项（仅展示） |
| `skip_reason` | Layer 2 AI | Layer 2 展示 | 若 action=skip 须填写原因（仅展示） |
| `pr_mapping` | Layer 2 AI | Layer 2 展示 | PR 映射聚合（整棵子树 Layer 3 不读，纯用户展示） |

### pr_mapping 子字段（仅 Layer 2 用户展示）

| 字段 | 用途 |
|------|------|
| `upstream_deps` | 上游依赖 PR/commit 列表 |
| `bugfix_deps` | bugfix 依赖 PR/commit 列表 |
| `revert_candidates` | 本地需 revert 的 PR/commit 列表 |

### pr_mapping 条目（每个子列表的元素）

| 字段 | 用途 |
|------|------|
| `pr_id` | PR 编号或"独立 commit" |
| `commits` | 该分组包含的 commit hash 列表 |
| `reason` | 依赖/revert 原因 |

### current_state（gatekeeper 自动维护）

| 字段 | 用途 |
|------|------|
| `phase` | 当前阶段（PHASE_2_MERGE 等） |
| `task_id` | 当前 task_id |
| `step` | 当前步骤（BUILD/COMMIT/REVIEW/DONE） |
| `status` | in_progress/pass/fail |
| `last_update` | 最后更新时间（ISO 8601） |

---

## revert_candidates.json（Layer 2 Subagent 产出，Layer 3 消费）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `schema_version` | Layer 2 Subagent | gate_check.sh | 接口版本校验 |
| `candidates[].commit_hash` | Layer 2 Subagent | **Layer 3 强依赖** | 需 revert 的 commit hash |
| `candidates[].subject` | Layer 2 Subagent | Layer 2 展示 | commit 标题 |
| `candidates[].ruling` | Layer 2 Subagent | **Layer 3 强依赖** | confirm（确认） / reject（拒绝） |
| `candidates[].ruling_reason` | Layer 2 Subagent | Layer 2 展示 | AI 判断理由 |
| `candidates[].revert_cmd` | Layer 2 Subagent | Layer 3 | 推荐 git revert 命令 |
| `keywords_used` | Layer 2 Subagent | Layer 2 展示 | 搜索用到的关键词 |
| `files_searched` | Layer 2 Subagent | Layer 2 展示 | 搜索范围 |

---

## deps_candidates.json（agent_patch_analysis 产出，Layer 3 消费）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `schema_version` | Layer 2 Subagent | gate_check.sh | 接口版本校验 |
| `dependencies[].commit_hash` | Layer 2 Subagent | **Layer 3 强依赖** | 上游依赖 commit hash |
| `dependencies[].subject` | Layer 2 Subagent | Layer 2 展示 | commit 标题 |
| `dependencies[].introduced_symbols` | Layer 2 Subagent | Layer 2 展示 | 引入的符号 |
| `dependencies[].ruling` | Layer 2 Subagent | **Layer 3 强依赖** | confirm / reject |
| `dependencies[].pull_cmd` | Layer 2 Subagent | Layer 3 | 推荐拉取命令 |
| `dependencies[].reason` | Layer 2 Subagent | Layer 2 展示 | 依赖原因 |

---

## patch_analysis.json（agent_patch_analysis 产出，Layer 3 消费）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `schema_version` | agent_patch_analysis | gate_check.sh | 接口版本校验 |
| `<task_id>.功能分类` | agent_patch_analysis | Layer 3 展示 | infra/driver/core/fs/net/sound/doc/bugfix |
| `<task_id>.功能概述` | agent_patch_analysis | Layer 3 展示 | 一句话功能描述 |
| `<task_id>.risk_level` | agent_patch_analysis | **Layer 3 强依赖** | 高/中/低，决定 AM 模式 |
| `<task_id>.risk_detail` | agent_patch_analysis | Layer 3 展示 | 风险详述 |
| `<task_id>.review_required` | agent_patch_analysis | Layer 3 展示 | 高/中/低 |
| `<task_id>.review_reason` | agent_patch_analysis | Layer 3 展示 | review 原因 |
| `<task_id>.conflicts_predicted` | agent_patch_analysis | **Layer 3 强依赖** | 预判冲突点，git am 前提前准备 |
| `<task_id>.special_notes` | agent_patch_analysis | **Layer 3 强依赖** | .rej 解决时逐条参考 |
| `<task_id>.depends_on` | agent_patch_analysis | Layer 3 展示 | 内部依赖 task_id 列表 |
| `<task_id>.blame_hits` | agent_patch_analysis | Layer 3 展示 | upstream git blame 追溯 |
| `<task_id>.execution_guide.am_mode` | agent_patch_analysis | **Layer 3 强依赖** | reject/3way，覆盖默认 AM 模式 |

### execution_guide

| 字段 | 类型 | 说明 |
|------|------|------|
| `am_mode` | string | reject（手动 .rej） / 3way（自动合并） |
| `conflict_strategy` | string/null | 冲突解决策略提示 |

---

## patch_symbols.json（Layer 2 脚本产出，Layer 2 AI 补全）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `subject` | 脚本 | Layer 2 展示 | patch 标题 |
| `introduced_symbols` | 脚本 | Layer 2 checkpoint 计算 | 本 patch 新增/修改的符号 |
| `referenced_symbols` | 脚本 | Layer 2 checkpoint 计算 | 本 patch 引用/调用的符号 |
| `changed_files` | 脚本 | Layer 2 展示 | 涉改文件列表 |
| `功能分类` | 脚本→AI 修正 | Layer 2 checkpoint 计算 | infra/core/driver/fs/net/sound/doc/bugfix |
| `feature_signature.keywords` | AI | Layer 2 Subagent | 搜索关键词 |
| `feature_signature.scope_dirs` | AI | Layer 2 Subagent | 限制搜索目录 |
| `depends_on` | AI | Layer 2 展示 | 内部依赖 task_id |
| `risk_level` | AI | Layer 2 展示 | 高/中/低 |
| `review_required` | AI | Layer 2 展示 | 高/中/低 |
| `blame_hits` | AI | Layer 2 展示 | bugfix commit 追溯 |
| `conflicts_predicted` | AI | Layer 2 展示 | 预判冲突点 |
| `special_notes` | AI | Layer 2 展示 | 合入注意事项 |
| `action` | AI | Layer 2 | apply/skip |
| `skip_reason` | AI | Layer 2 展示 | 若 skip 的原因 |

---

## samples_summary.json（Layer 2 抽样检测产出，Layer 2 内部消费）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `schema_version` | Layer 2 脚本 | gate_check.sh | 接口版本校验 |
| `patches[].task_id` | 脚本 | Layer 2 AI | patch 标识 |
| `patches[].files` | 脚本 | Layer 2 Subagent | 涉改文件（限定搜索范围） |
| `patches[].symbol_samples` | 脚本 | Layer 2 AI | 符号样本 |
| `patches[].keyword_samples` | 脚本 | Layer 2 AI | 关键词样本 |
| `patches[].keywords` | 脚本 | Layer 2 Subagent | Agent 扩展搜索用 |
| `total_patches` | 脚本 | Layer 2 展示 | patch 总数 |

---

## duplicate_analysis.json（Layer 2 AI 分析产出，Layer 2 内部消费）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `schema_version` | Layer 2 AI | gate_check.sh | 接口版本校验 |
| `patch_duplicate_map` | Layer 2 AI | Layer 2 展示 | 每个 patch 的匹配结果 |
| `keywords_summary` | Layer 2 AI | Layer 2 Subagent | Agent 搜索用关键词 |
| `recommended_scene` | Layer 2 AI | Layer 2 展示 | AI 推荐 upgrade/backport |

---

## state.json（orchestrator 产出，全链路消费）

| 字段 | 生产者 | 消费者 | 用途 |
|------|--------|--------|------|
| `session_id` | orchestrator | 恢复 | 会话标识 |
| `kernel_repo` | orchestrator | 恢复 | 目标仓库 |
| `output_dir` | orchestrator | 恢复 | 输出目录 |
| `current_layer` | orchestrator | 恢复 | 当前所在层 |
| `layer_status.<layer>.status` | orchestrator | 恢复 | pending/in_progress/completed/failed |
| `all_layers_completed` | orchestrator | 恢复 | 是否全部完成 |

---

## Layer 3 强依赖字段汇总

以下字段是 Layer 3 正确执行**必须**正确填充的，其余字段缺失不影响执行：

| 来源 | 字段 |
|------|------|
| config.json | `kernel_repo_path`, `kernel_arch`, `build_cmd`, `scene` |
| merge_tasks.json | `seq`, `task_id`, `patch_file`, `action`, `pre_revert`, `depends_on`, `build_checkpoint` |
| patch_analysis.json | `<task_id>.risk_level`, `<task_id>.conflicts_predicted`, `<task_id>.special_notes`, `<task_id>.execution_guide.am_mode` |
| revert_candidates.json | `candidates[].commit_hash`, `candidates[].ruling` |
| deps_candidates.json | `dependencies[].commit_hash`, `dependencies[].ruling` |
