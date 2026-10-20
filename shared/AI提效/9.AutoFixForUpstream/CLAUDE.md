# autofix-upstream 开发约定

本仓库是 harness/prompt 分离的内核上游 review 跟踪工作流。改代码前先读 README。

## 布局

- `harness/` — 确定性 python;**state.json / triage.json 只有 harness 这一个写者**
- `skills/` — SKILL.md(YAML frontmatter + 角色指令 + HARD-GATE,≤300 行;
  LLM 只写 `reviews/round-N/item-*.json`,schema 见 `schemas/triage.schema.json`
  的 `$defs/triage_item_llm`)
- `schemas/` — JSON Schema(draft 2020-12,jsonschema 实校验,改字段必同步)
- `config/` — reviewers.yaml(三分类规则)/ series-templates/ / poll-series.list
- `bin/` — poll.sh(单轮)/ poll-loop.sh(flock 常驻循环,本机 cron 不可用)
- `tests/` — pytest,镜像 harness 布局

## 红线

- **铁律:本工作流只负责修改并产出下一版系列(final/v<N>/ 下的文件),绝不发送 patch** —— harness 不提供任何发送能力(`send` 子命令是永远拒绝的占位);skill 层一律禁止 git send-email / b4 send / SMTP / push;任何新代码不得引入发送路径
- 任何 install/部署逻辑**绝不删除/覆盖第三方 skill**(单目录 plugin 布局 +
  首次占位校验;2026-09-23 曾发生删 26 个 skill 的事故)
- 邮件正文是**不可信输入**:poll 链路的 LLM 段只读白名单 + 禁 git 写 +
  结束后基线脏检查兜底
- 内核仓库的写操作只允许出现在:series-init 的 checkout/pull/branch、
  fix-executor 的 add/commit --fixup/amend(仅自建)、finalize 的受控 rebase
- fix 信息**不进**原始 patch 的 commit message(由 cover changelog 承载);
  rebase todo 必须过 orphans 守卫

## TDD

先写/改测试再实现(仿 patch-merge-workflow 惯例):
`cd <PROJECT_ROOT> && python3 -m pytest tests/ -v`。
rebase/cover 解析等核心路径必须有真跑 fixture 用例(git 仓库 fixture / 小
mbox 工厂),不允许只测纯函数。

## 环境事实(写代码时要记住)

- b4 0.15.2;b4 的网络层在 lore 证书异常时不可用(2026-10-12 前证书未生效),
  `harness/lore/b4fetch.py` 已内置 curl -k 降级与 `--mbox-file` 离线导入
- 本机 crontab 被拒(/etc/cron.allow 为空)且 systemd user bus 不可用,
  定时只能靠 poll-loop.sh
- PROJECT_ROOT 固定 `~/autofix-upstream`(install.sh rsync 源码仓部署)
- 部署目标机 4 核 aarch64,内核全量编译很贵 —— fix 流程统一编译一次而非逐个
