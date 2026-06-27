# duplicate_analysis.json Schema

Layer 2 步骤 3b AI 分析产出，Layer 2 内部消费（步骤 4 Subagent 输入 + 步骤 3d scene 判定）。当前 schema_version: `1.0`。

## 完整 Schema（简化版，基于抽样）

```json
{
  "schema_version": "1.0",
  "patch_duplicate_map": {
    "0001": [
      {
        "match_type": "sampling",
        "match_count": 7,
        "match_level": "高匹配",
        "matched_files": ["arch/arm64/kvm/hdbss.c"],
        "matched_samples": ["static int hdbss_init", "#define HDBSS_ENABLE"],
        "ruling": "疑似旧版本",
        "ruling_reason": "抽样检测发现7行匹配，建议 upgrade 模式"
      }
    ]
  },
  "keywords_summary": {
    "0001": ["HDBSS", "FEAT_HDBSS", "DBM"],
    "0002": ["HDBSS", "stage2_map"]
  },
  "total_patches": 5,
  "patches_with_matches": 3,
  "recommended_scene": "upgrade"
}
```

## 字段说明

| 字段 | 说明 |
|------|------|
| `patch_duplicate_map.<task_id>` | 该 patch 的匹配检测结果数组，无匹配则为 `[]` |
| `match_type` | 固定 `"sampling"`（快速抽样检测，非完整 commit 定位） |
| `match_count` | 匹配行数 |
| `match_level` | `"无匹配"` / `"低匹配"` / `"中匹配"` / `"高匹配"` |
| `ruling` | AI 判定的处理建议 |
| `ruling_reason` | 判定依据说明 |
| `keywords_summary.<task_id>` | 该 patch 的关键词列表（供 agent_target_revert 扩展搜索） |
| `recommended_scene` | AI 推荐的场景（`upgrade` / `backport`），仅供参考，最终由用户选择 |

## 完整版 Schema（detect_duplicate.py 产出，备用）

```json
{
  "schema_version": "1.0",
  "patch_duplicate_map": {
    "0001": [
      {
        "commit": "abc123",
        "similarity": 95.0,
        "level": "高匹配",
        "pr_info": {"pr_id": "PR #123", "source": "commit_msg_link"},
        "matched_patch": "0001",
        "patch_add_line_count": 120,
        "common_lines": 114
      }
    ]
  },
  "pr_aggregation": {
    "PR #123": {
      "commits": ["abc123", "def456"],
      "matched_patches": [],
      "decision": {
        "strategy": "revert 匹配的 commits（逐个）",
        "urgency": "建议",
        "coverage_rate": 66.7,
        "total_commits": 3,
        "high_match_count": 2,
        "revert_targets": ["abc123", "def456"]
      }
    }
  },
  "global_revert_order": [],
  "thresholds": {
    "single_similarity_high": 80,
    "single_similarity_medium": 50,
    "pr_coverage_whole": 75
  }
}
```

### revert 决策规则（完整版）

覆盖率仅影响紧急程度，revert 始终以单个 commit 为粒度，禁止按 PR 整体 revert。

| 覆盖率 | 行为 | urgency |
|--------|------|---------|
| >= 75% | revert 匹配的 commits（逐个） | 必须 |
| 50-74% | revert 匹配的 commits（逐个） | 建议 |
| < 50% | 不自动 revert | 无须 |
