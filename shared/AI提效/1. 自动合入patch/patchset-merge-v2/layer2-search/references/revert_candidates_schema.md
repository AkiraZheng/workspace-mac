# revert_candidates.json Schema

Layer 2 步骤 4 agent_target_revert Subagent 产出，Layer 3 消费。当前 schema_version: `1.0`。

## 完整 Schema

```json
{
  "schema_version": "1.0",
  "candidates": [
    {
      "commit_hash": "abc123",
      "subject": "HDBSS 初始化实现 v2",
      "similarity_score": 0.82,
      "ruling": "confirm",
      "ruling_reason": "旧版本 HDBSS 实现，与上游 patch 0001 功能重叠",
      "revert_cmd": "git revert abc123"
    }
  ],
  "keywords_used": ["HDBSS", "FEAT_HDBSS", "DBM"],
  "files_searched": ["arch/arm64/kvm/hdbss.c"]
}
```

## 字段说明

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `candidates[].commit_hash` | ✓ | 需 revert 的 commit hash（**必须是单个 commit，禁止 merge commit**） |
| `candidates[].subject` | ✓ | commit 标题 |
| `candidates[].similarity_score` | - | 相似度评分（0.0-1.0） |
| `candidates[].ruling` | ✓ | `confirm`（确认 revert）或 `reject`（拒绝） |
| `candidates[].ruling_reason` | ✓ | AI 判断理由 |
| `candidates[].revert_cmd` | ✓ | 推荐 revert 命令 |
| `keywords_used` | ✓ | 搜索使用的关键词列表 |
| `files_searched` | ✓ | 搜索范围文件列表 |

## agent_target_revert 行为（按 scene）

### upgrade 模式：AI 深度搜索
1. 读取 `duplicate_analysis.json` 中的 `keywords_summary`
2. 读取 `samples_summary.json` 中的 `files`（限定搜索范围）
3. 扩展搜索：关键词聚合（`git log --grep`）→ Revert 追溯（`git log --grep="Revert"`）→ 符号追溯（`git log -S`）→ 文件追溯（`git log --`）
4. 深入理解：读取每个候选 commit 的 message + diff，AI 判断 confirm/reject
5. merge commit 必须展开为子 commit，禁止写入 merge commit hash
6. 去重合并后输出

### backport 模式：严格审核
1. 读取抽样检测结果
2. 不启动扩展搜索
3. match_count >= 6 → 暂停提示用户确认
4. match_count < 6 → 标记为 reject（误报或极相似代码）
