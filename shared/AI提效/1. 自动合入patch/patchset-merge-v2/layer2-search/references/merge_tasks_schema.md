# merge_tasks.json Schema

Layer 2 步骤 8-9 产出，Layer 3（执行层）和 Layer 4（输出层）消费。**必须严格按此 schema，不可自行增减或重命名字段。** 当前 schema_version: `1.0`。

> **存储路径**：`$OUTPUT_DIR/merge_tasks.json`

## 完整 Schema

```json
{
  "schema_version": "1.0",
  "patchset_info": {
    "source": "<来源描述>",
    "download_method": "b4|wget|local",
    "total_patches": 5,
    "target_kernel": "$KERNEL_REPO_PATH",
    "target_branch": "$KERNEL_BRANCH",
    "build_target": "$BUILD_CMD"
  },
  "workflow_hints": {
    "BUILD_FIX": "只修改 patch 相关文件；config 问题临时修改后 git restore；错误超过 10 个时暂停等待用户决策",
    "COMMIT_ORDER": "必须按 merge_order 顺序，每个 patch 一个 commit",
    "REVERT_POLICY": "逆序 revert（最新→最旧），每 revert 一个就 commit 一个",
    "BUILD_REQUIREMENT": "编译整个仓库 $BUILD_CMD -j$(nproc)，error=0 + 产物存在"
  },
  "current_state": null,
  "global_revert_order": [],
  "deps_order": [],
  "merge_order": [
    {
      "seq": 1,
      "task_id": "0001",
      "status": "pending",
      "patch_file": "/tmp/patches/0001-xxx.patch",
      "subject": "patch subject",
      "author": "patch author",
      "files_changed": ["file1.c", "file2.h"],
      "功能分类": "driver",
      "introduced_symbols": ["kbase_reg_write", "HDBSS_ENABLE_BIT"],
      "referenced_symbols": ["kvm_stage2_get_level"],
      "action": "apply",
      "skip_reason": null,
      "pre_revert": [],
      "depends_on": [],
      "risk_level": "低",
      "review_required": "低",
      "blame_hits": [],
      "duplicate_info": {"level": "无重复", "detail": ""},
      "conflicts_predicted": [],
      "special_notes": "",
      "build_checkpoint": false,
      "checkpoint_reason": null,
      "pr_mapping": {
        "upstream_deps": [],
        "bugfix_deps": [],
        "revert_candidates": []
      },
      "execution_log": [],
      "state_log": []
    }
  ]
}
```

## merge_order / deps_order 任务字段说明

| 字段 | 必填 | 类型 | 说明 |
|------|:--:|------|------|
| `seq` | ✓ | int | 执行序号，从 1 开始递增。merge_order 先排，deps_order 从 merge_order 最后一个 seq+1 开始 |
| `task_id` | ✓ | string | 补零 4 位（如 `"0001"`）或 `dep-001`~`dep-00N` |
| `status` | ✓ | string | `pending` / `in_progress` / `done` / `blocked` / `skipped` / `failed` |
| `patch_file` | ✓ | string | .patch 文件的绝对路径 |
| `subject` | ✓ | string | patch 标题 |
| `author` | ✓ | string | patch 作者 |
| `files_changed` | ✓ | list | 涉改文件路径列表 |
| `功能分类` | ✓ | string | infra/core/driver/fs/net/sound/doc/bugfix |
| `introduced_symbols` | ✓ | list | 本 patch 新增/修改的符号名，用于跨 patch 依赖统计和 checkpoint 计算 |
| `referenced_symbols` | ✓ | list | 本 patch 调用/引用的符号，用于依赖统计 |
| `action` | ✓ | string | `apply`（需要合入）或 `skip`（跳过） |
| `skip_reason` | - | string/null | 若 action=skip，必须填写具体原因 |
| `pre_revert` | ✓ | list | 需先 revert 的本地 commit hash（**必须是单个 commit hash，禁止 merge commit hash**） |
| `depends_on` | ✓ | list | 前置 task_id 列表 |
| `risk_level` | ✓ | string | `高` / `中` / `低` |
| `review_required` | ✓ | string | `高` / `中` / `低` |
| `blame_hits` | ✓ | list | bugfix commit 列表 |
| `duplicate_info` | ✓ | dict | `{"level": "无重复|高匹配|中匹配", "detail": "...", ...}` |
| `conflicts_predicted` | ✓ | list | 预判冲突点 |
| `special_notes` | ✓ | string | 合入注意事项 |
| `build_checkpoint` | ✓ | bool | 是否在此点做编译验证 |
| `checkpoint_reason` | - | dict/null | checkpoint 判定依据：`{rules_triggered, primary_reason, reverse_dep_detail}` |
| `pr_mapping` | ✓ | dict | PR 映射聚合（见下方） |
| `execution_log` | ✓ | list | 初始 `[]`，Layer 3 执行时追加 |
| `state_log` | ✓ | list | gatekeeper 自动追加 `[{step, time, result, ...}]` |

## pr_mapping 字段说明

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `upstream_deps` | ✓ | 上游依赖 PR/commit 列表 |
| `bugfix_deps` | ✓ | bugfix 依赖 PR/commit 列表 |
| `revert_candidates` | ✓ | 本地需 revert 的 PR/commit 列表 |

### pr_mapping 条目结构

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `pr_id` | ✓ | PR 编号（如 `"PR #123"`）或 `"独立 commit"` |
| `pr_url` | - | PR 链接 |
| `commits` | ✓ | 该分组包含的 commit hash 列表 |
| `cover_letter_msgid` | - | lore.kernel.org cover letter message-id |
| `download_cmd` | - | 推荐拉取命令 |
| `revert_cmd` | - | 推荐 revert 命令（仅 revert_candidates） |
| `subject` | - | PR/subject 描述 |
| `reason` | ✓ | 依赖/revert 原因 |
| `urgency` | ✓ | `必须` / `建议` / `无须`（仅 revert_candidates） |

## 顶层字段说明

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `schema_version` | ✓ | 接口版本号，当前 `"1.0"` |
| `patchset_info` | ✓ | 来源/目标/架构基本信息 |
| `workflow_hints` | ✓ | 关键流程提示 |
| `current_state` | ✓ | 当前执行状态（gatekeeper 自动管理） |
| `global_revert_order` | ✓ | PR 聚合的全局 revert 列表 |
| `deps_order` | ✓ | 上游依赖 patch 列表（初始 `[]`） |
| `merge_order` | ✓ | 主体合入任务列表 |

## current_state 字段说明

| 字段 | 说明 |
|------|------|
| `phase` | 当前阶段（如 `PHASE_2_MERGE`） |
| `task_id` | 当前 task_id |
| `step` | 当前步骤（`BUILD`/`COMMIT`/`REVIEW`/`DONE`） |
| `status` | `in_progress`/`pass`/`fail` |
| `last_update` | 最后更新时间（ISO 8601） |

## state_log BUILD 记录格式

```json
{
  "step": "BUILD",
  "time": "2025-05-27T15:00:00Z",
  "result": "pass",
  "error_count": 0,
  "product": "arch/arm64/boot/Image",
  "build_target": "Image modules",
  "module_dirs": ["drivers/gpu/drm"],
  "module_count": 5
}
```

> - `build_checkpoint=true` → gatekeeper 记录 BUILD pass/fail
> - `build_checkpoint=false` → 不调用 gatekeeper BUILD，state_log 无 BUILD 记录

## 恢复机制

```bash
# 任务启动时检查
python3 gatekeeper.py --merges-file merge_tasks.json --restore
# exit 10 → 有未完成工作，需要恢复
# exit 0  → 无未完成工作

# 恢复后清除标记
python3 gatekeeper.py --merges-file merge_tasks.json --restore --clear
```

Layer 3 执行顺序：先遍历 `deps_order`（若有），再遍历 `merge_order`，各自按 `seq` 升序。
