# merge-patchset

Linux 内核 patchset 多 Agent 自动合入与冲突解决 Skill。

- 26.5.23：当前版本在opencode+ds场景下执行稳定，在glm下不咋行

## 功能

- 从 lore.kernel.org、URL 或本地目录获取 patchset
- 多 Agent 并行分析每个 patch 的依赖、bugfix、冲突风险
- PR 聚合：优先找整个 PR 的提交内容，避免遗漏分散 patch
- 自动拉取上游依赖 patch（Phase 1.5 末尾）
- 串行合入：`git am --3way` → 冲突解决 → **整个仓库编译验证** → commit → review
- 每 patch 落盘分析报告，最终汇总
- 10 轮自动重试上限，超限后输出具体代码级方案供用户选择
- 跨 patch 修复：rebase → amend → 重编译 → continue

## 依赖

| 工具 | 必需 | 说明 |
|------|:----:|------|
| python3 | ✓ | 运行脚本 |
| git | ✓ | 版本控制 |
| make | ✓ | 内核编译验证 |
| b4 | 推荐 | 从 lore.kernel.org 下载 patchset（pip install b4） |
| wget | 推荐 | 从 URL 下载 patchset |
| pytest | 可选 | 安装时运行测试 |

## 安装

```bash
cd /path/to/patchset-merge
bash install.sh
```

`install.sh` 会：
1. 检测并尝试安装缺失工具（dnf→yum→apt→pacman→pip）
2. 校验文件完整性
3. 运行单元测试
4. 部署到 skill 目录
5. 验证 symlink

## 使用

用户一句话描述需求，skill 自动提取配置：

```bash
# 场景 A：从 lore.kernel.org 下载
合入 <message-id> 到 ~/code/openeuler/kernel 的 patch-xxx 分支

# 场景 B：本地 patch + 指定 upstream（用于依赖搜索）
把 /mnt/shared/originPatch/dumpStage2 合入到 /root/code/openeuler/kernel，
upstream 是 ~/code/linux/linux

# 场景 C：本地 patch，无 upstream（降级为 metadata 推断）
将 /mnt/shared/originPatch/HDBSS_v3 合入到 /root/code/openeuler/kernel，
没有源仓库
```

skill 自动设置的环境变量：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `KERNEL_REPO_PATH` | 目标内核仓库 | 从用户输入解析 |
| `KERNEL_BRANCH` | 操作分支 | 从用户输入解析或当前分支 |
| `UPSTREAM_REPO_PATH` | 上游 Linux 仓库（依赖搜索用） | `~/.cache/linux-upstream`（自动 clone） |
| `KERNEL_ARCH` | 目标架构 | 自动检测 |
| `BUILD_CMD` | 编译命令 | 自动构造 |

**依赖搜索需要上游仓库**：Phase 1 的 `git blame`、`git log -S`、`git log --grep="Fixes:"` 均在 `$UPSTREAM_REPO_PATH` 上执行。若无上游仓库，降级为仅从 patch metadata 推断依赖。

skill 工作流：
```
Phase 0:  下载 → /tmp/patches/000N-*.patch + metadata.json
          → 创建 $KERNEL_REPO_PATH/patch_analysis/
Phase 1:  并行分析（只读，不写文件）
Phase 1.5: 主 Agent 汇总 → patch_analysis/merge_tasks.json + analysis_cache.json
          → 全局预览 → 用户确认 → 拉取上游依赖（自动）
Phase 2:  串行 Merge → 编译验证 → 每 patch commit 后落盘 analyse.md
Phase 3:  汇总 → patch_analysis/summary.md → 检查提醒
Phase 4:  清理中间产物（可选，patch_analysis/ 不清理）
```

## 输出

```
$KERNEL_REPO_PATH/patch_analysis/
  0001-<name>-analys.md       # 每个 patch 的分析报告
  0002-<name>-analys.md
  ...
  summary.md                   # 汇总报告
  merge_tasks.json             # 合并任务调度文件
  analysis_cache.json          # Phase 1 分析缓存
  0001-diff.txt ~ 000N-diff.txt # 每 patch 的 diff 报告

/tmp/patches/
  0001-*.patch ~ 000N-*.patch  # 下载的原始 patch 文件（可清理）
  deps/                         # 上游依赖 patch（可清理）
  patchset.metadata.json        # patchset 元数据（可清理）
```

每份分析报告包含：
- 功能描述与关联模块
- 依赖分析（高版本/bugfix/前置 patch）
- PR 映射聚合（优先按 PR 分组）
- Revert 需求评估（必要性等级 + revert_cmd）
- 风险程度（高/中/低）
- 人工 review 需求度
- 建议验证冒烟内容
- 合入实际经验
- 与源 patch 的完整 diff
- 编译验证记录

## 架构

```
SKILL.md                      # 主 Skill 文件
AGENTS.md                     # 开发工作区配置
scripts/                      # 确定性脚本
  download_patches.py           # 统一下载入口（b4/wget/本地）
  generate_diff_report.py       # diff 对比生成
  topo_sort.py                  # 依赖拓扑排序
references/                   # 参考文档
  diagnostic-guide.md           # Ours/Theirs 冲突诊断决策树
  output-templates.md           # 输出模板 + schema 定义
  code-review-expert/           # 捆绑 review skill
features/                     # 草案设计 & 待办
  topo_sort.md                  # 拓扑排序设计稿
  revert-lookup.md              # revert 依赖查找设计稿
  todo-issue.md                 # 已知问题及改进方向
examples/                     # 实际运行案例
  1-DS-HDBSS-v3-merge-to-oe/    # DS 模型运行示例
  2-glm-HDBSS-v3-merge-to-oe/   # GLM5 模型运行示例
docs/                         # 设计文档（specs/plans）
tests/                        # 单元测试（113 个）
  test_download_patches.py      # 下载脚本测试
  test_generate_diff_report.py  # diff 报告测试
  test_topo_sort.py             # 拓扑排序测试
  test_schema.py                # merge_tasks.json + analysis_cache.json schema 校验
install.sh                    # 一键安装部署脚本
```

## 核心约束

1. 逐个合入 + 逐个 commit
2. 仅在出问题时与用户交互（冲突超限/循环依赖/重复 patch）
3. 每 commit 后 code review
4. Revert 逐个 commit（逆序），优先按 PR 整体 revert
5. **每 patch 必须整个仓库编译验证**：0 error + 最终产物存在，禁止跳过或只编译部分文件
6. Merge 串行，分析并行
7. 中文输出
8. 只取改动行（`+`/`-` 开头的实际修改行）
9. 修改严格归所属 patch
10. 编译通过 + 功能正常是第一指标
11. 结构化文件（JSON）存储到 `patch_analysis/`，永久保留不清理
