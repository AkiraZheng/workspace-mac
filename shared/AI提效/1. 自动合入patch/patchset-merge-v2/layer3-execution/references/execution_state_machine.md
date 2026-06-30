# 执行状态机

Layer 3 的 7 步状态机定义。每个 patch 串行经过以下步骤，gatekeeper.py 强制执行前置依赖。

## 状态机流程

```
PRECHECK → PRE_REVERT → APPLY → VERIFY_INTENT → BUILD → COMMIT → REVIEW → RECORD → DONE
```

## 步骤说明

| 步骤 | 说明 | 前置依赖 | build_checkpoint 行为 |
|------|------|---------|----------------------|
| PRECHECK | 检查 patch 文件存在、工作区干净 | 无 | 始终执行 |
| PRE_REVERT | revert 旧版本 commit | 无 | Phase 1 批量执行，Phase 3 跳过（标记 skip） |
| APPLY | git am --3way --reject + 处理 .rej | 无 | 始终执行 |
| VERIFY_INTENT | verify_patch_intent.py 校验 | APPLY | 始终执行 |
| BUILD | 编译验证 | 无（动态按 build_checkpoint） | checkpoint=true 时执行，false 时跳过 |
| COMMIT | git commit | VERIFY_INTENT + BUILD（仅 build_checkpoint=true 时） | 始终执行 |
| REVIEW | linux-kernel-review skill | COMMIT | 始终执行 |
| RECORD | gatekeeper --check | REVIEW | 始终执行 |
| DONE | 标记完成 | BUILD + COMMIT | — |

## 动态前置依赖

`COMMIT` 的前置 `BUILD` 是动态的：
- `build_checkpoint=true` → COMMIT 必须有 BUILD pass 记录
- `build_checkpoint=false` → COMMIT 无 BUILD 前置依赖

## gatekeeper.py 用法

```bash
# 标记步骤开始
python3 gatekeeper.py --merges-file merge_tasks.json --task-id 0001 \
  --step BUILD --result in_progress

# 标记步骤完成
python3 gatekeeper.py --merges-file merge_tasks.json --task-id 0001 \
  --step BUILD --result pass --error-count 0 --product "Image:39M"

# 门禁检查（检查前置步骤是否完成）
python3 gatekeeper.py --merges-file merge_tasks.json --task-id 0001 \
  --step COMMIT --check

# 恢复模式
python3 gatekeeper.py --merges-file merge_tasks.json --restore
python3 gatekeeper.py --merges-file merge_tasks.json --restore --clear
```

## PRE_REVERT 特殊逻辑

Phase 1 批量提取所有 task 的 `pre_revert` commit hash（去重），逆序逐个执行 `git revert`。
Phase 3 不再执行 PRE_REVERT（标记为 skip）。
