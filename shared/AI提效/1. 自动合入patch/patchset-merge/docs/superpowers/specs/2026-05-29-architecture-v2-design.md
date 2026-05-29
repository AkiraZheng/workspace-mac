# Merge-Patchset Skill Architecture v2

> 从 v1 的 "Agent 按 patch 平分" 改为 "按职责分层" 的确定性架构。

## 1. 整体架构

```
                    用户输入
                       |
               +-------+--------+
               |  Phase 0: 下载   |  脚本: download_patches.py
               |  + 场景问询      |  AI: 展示旧版本 commit 列表, 用户选 U/B
               +-------+--------+
                       |
    +==============================================+
    |   Layer 1: 脚本层 (并行, 确定性, 不依赖 AI)     |
    |                                              |
    |  detect_duplicate.py  -- 三层下降做 revert     |
    |  topo_sort.py         -- 符号依赖图           |
    |  calculate_build_     -- 编译验证点            |
    |    checkpoints.py                            |
    +==============================================+
                       |
    +==============================================+
    |   Layer 2: 语义层 (并行, AI 只读不写文件)       |
    |                                              |
    |  agent_analysis -- 功能理解 + 依赖标注 + 风险   |
    |  agent_revert   -- 审核 L1 revert 候选, 裁决   |
    +==============================================+
                       |
    +==============================================+
    |   Layer 3: 主 Agent (串行, 唯一裁决入口)       |
    |                                              |
    |  汇总 L1+L2 -- 冲突判定 -- 用户确认            |
    |  -- merge_tasks.json + analysis_cache.json    |
    +==============================================+
                       |
    +==============================================+
    |   Phase 2: 串行 Merge                        |
    |                                              |
    |  PRECHECK -- PRE_REVERT -- APPLY              |
    |  -- BUILD (编译门禁) -- COMMIT -- agent_review |
    |  -- gatekeeper 每步落盘                        |
    +==============================================+
```

## 2. Agent 职责定义

### agent_analysis

| 维度 | 定义 |
|------|------|
| 输入 | /tmp/patches/000N-*.patch (全部), $KERNEL_REPO_PATH, analysis_cache.json (L1 已填充 introduced/referenced_symbols) |
| 输出 | analysis_cache.json 追加字段: `analyzed_notes` (功能描述/模块关联/风险), `dep_hints` (commit message 中的依赖线索) |
| 规则 | 优先读 commit message 再读 diff; 功能分类沿用现有规则; 风险: 高(核心路径/锁/内存) / 中(驱动逻辑) / 低(doc/log) |
| 约束 | 只读, 不调 git write, 不写 merge_tasks |

### agent_revert

| 维度 | 定义 |
|------|------|
| 输入 | duplicate_analysis.json (L1 脚本产出), 场景 (upgrade/backport), $KERNEL_REPO_PATH |
| 输出 | duplicate_analysis.json 追加字段: `revert_ruling` (confirm/reject/partial), `revert_ruling_note` (调整理由) |
| 核心职责 | 审核 L1 脚本的 revert 候选, 不是自己找 |
| upgrade 模式 | 批次 ≥3 commits → 默认 confirm 全部; 排除无关 bugfix (如 memory leak); 按时间排序输出 |
| backport 模式 | diff ≥80% → confirm; diff 50-79% → partial(用户定); diff <50% → reject |

### agent_review (Phase 2 中)

| 维度 | 定义 |
|------|------|
| 触发 | 每 commit 后 |
| 实现 | 调用 code-review-expert skill (已有) |
| 处理 | Must Fix → 标记需 rebase amend; Suggest → 记录不阻塞 |

## 3. Revert 检测三层策略（全限定涉改目录）

```
策略 1: keyword + author 聚合 (主策略)
  -- 从新 patch 提取专用关键词 (HDBSS, HDBSSF, FEAT_HDBSS, DBM)
  -- git log --grep=<kw> --author=<author> -- <patch_dirs>   仅当前分支
  -- 同 author + 3 天窗口分组 → ancestry-path 补全全部子 commit

策略 2: diff + symbol 匹配 (fallback)
  -- 现有 search_candidates: diff_grep + -S pickaxe + 文件最近 commit
  -- similarity 计算 combined_similarity(diff, symbol)
  -- upgrade 模式阈值 30/15, backport 模式阈值 80/50

策略 3: revert commit 追溯 (补充, 仅当前分支)
  -- git log --grep="^Revert" --grep=<专用kw> -- <patch_dirs>
  -- 过滤: subject 以 "Revert" 开头 + 含专用关键词 + 涉改文件重叠
  -- 解析 "This reverts commit <hash>" → _extract_merge_commits
```

## 4. 编译 + 落盘门禁

### 编译门禁

- build_checkpoint=true 的 task: 必须执行完整 make + 产物验证
- 编译 exit code ≠ 0 -- 禁止进入 COMMIT
- 产物缺失 (Image 不存在) -- 禁止进入 COMMIT
- gatekeeper.py --step COMMIT --check 强制校验, exit != 0 则 agent 必须停在 BUILD

### 落盘门禁

- 每个 task 的 execution_log 实时追加到 merge_tasks.json
- 每步开始写 in_progress, 完成写 pass/fail
- 崩溃恢复: 读 merge_tasks.json -- 找 status != done -- 原地继续
- 禁止静默跳过: BUILDPASS/COMMITPASS/REVIEWDONE 标签必须显式输出

## 5. 场景分类

- Phase 0 末尾: L1 先跑普通模式 detect_duplicate
- 若检测到 revert 候选 -- 展示给用户, 询问 U(升级) / B(backport)
- 用户选 U -- L1 用 --version-upgrade 重跑; 选 B -- 用当前结果
- 删除 ask_scene.py (交互逻辑写入 SKILL.md + L3 主 Agent)

## 6. 文件变更清单

| 文件 | 动作 |
|------|------|
| AGENTS.md | 更新硬性约束 + Agent 架构 + 同步路径 |
| SKILL.md | 更新 Phase 0(场景问询) + Phase 1(三层架构) + Phase 2(编译门禁) |
| detect_duplicate.py | 保留, 已有 --version-upgrade 和三降策略 |
| ask_scene.py | 删除 |
| output-templates.md | 更新 Agent 输出格式 |
| agent-design.md | 新建, Agent 职责参考 |
