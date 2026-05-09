# Patchset Merge 实施步骤

## Step 1: 创建项目结构和核心模块
- [√] 创建目录结构
- [√] 实现 b4_installer.py - b4 工具安装和版本检查
- [√] 实现 patchset_downloader.py - 从 lore.kernel.org 下载 patchset
- [√] 实现 diff_tracker.py - 追踪 patchset 应用后的差异
- [√] 实现 conflict_resolver.py - 冲突解决策略（patchset 内容优先）
- [√] 实现 merger.py - 核心 Merge 引擎
- [√] 实现 skill.py - Claude Code Skill 入口
- [√] 实现 tests/test_patchset_merge.py - 单元测试
- [√] 创建 Claude Code Command 文件 .claude/commands/merge-patchset.md

## Step 2: 运行测试验证
- [√] 运行 pytest 验证所有单元测试通过
- [√] 验证代码可以正常 import

## Step 3: 提交代码
- [√] git add -A && git commit -m "feat: add patchset merge skill - Task 1"

