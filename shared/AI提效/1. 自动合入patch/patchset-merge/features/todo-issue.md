# 待解决问题清单

## 已解决

| 问题 | 解决方式 |
|------|---------|
| AI 上下文爆掉冲掉记忆 | 每步落盘 + gatekeeper 恢复机制 + Phase 3 硬编码提醒 |
| GLM5 不按规则执行编译验证 | AGENTS.md 编译门禁 (10-13) + gatekeeper --check 硬性校验 |
| diff 输出内容不清晰 | generate_diff_report.py 重写 |
| revert 检测基于 author 不科学 | **改为关键词+目录+时间窗口聚合**，不限作者 |
| revert commit 排序错误 | generate_revert_plan.py 按 git timestamp 逆序 |
| 编译 checkpoint 设计不良 | calculate_build_checkpoints.py 8 级规则，revert 走 Rule 4(末patch强制) |
| 缺少版本升级/backport 场景分类 | Phase 0 末尾交互问询，deterministic |

## 进行中

| 问题 | 状态 |
|------|------|
| 没有执行 review skill | 🟡 待处理，P2 |
| ask_scene.py 冗余 | ✅ 已删除，逻辑写入 SKILL.md + L3 |

## 新增

| 问题 | 说明 | 优先级 |
|------|------|--------|
| feature_signature 字段由 AI 填充 | agent_analysis 需落地此字段，目前脚本 fallback 可用 | 中 |
| 关键词长文本 (如 "Hardware Dirty Bit State Save") 在 grep 中无效 | 需在 _search_keyword_commits 中优先取全称中出现的缩写 | 低 |
| 高版本源端合入的 upstream 搜索未全链路测试 | 场景 B 的实际验证不足 | 中 |
