# autofix-upstream — 内核社区 review 意见跟踪与自动修复工作流

跟踪 lore.kernel.org 上自己 patch 系列的社区检视意见,**区分人为 reviewer /
sashiko 类 AI 检视 / 测试机器人**,深度甄别有效性并生成 bugfix;意见稳定后把
bugfix **fixup 合回原始 patch**(信息进 v6 cover 的 changelog,不污染原 patch
的 commit message),产出下一版系列。

> **铁律:本工作流只负责修改并产出下一版系列(`final/v<N>/` 下的文件),绝不发送 patch。**
> 禁止 git send-email / b4 send / SMTP / push;发送永远由用户在工作流之外人工完成
> (CLI 的 `send` 子命令是永远拒绝的占位,测试固化此规则)。

首个实例:HDBSS v5 → v6(kvmarm,`[PATCH v5 00/15] KVM: arm64: FEAT_HDBSS
support for stage-2 dirty tracking`)。

## 架构(harness / prompt 分离)

```
确定性问题(网络拉取/增量/关联/rebase/导出) -> harness/(python, 唯一写 state/triage.json)
AI 判断(意见甄别/改码/changelog 措辞)      -> skills/*/SKILL.md
```

- 系列工作区在内核仓库 `<repo>/.autofix/<series-id>/`(自动加入
  `.git/info/exclude`,不污染 git status):
  `series.yaml`(静态配置)/ `state.json`(动态状态)/ `triage.json`(台账数据
  真源)+ `triage.md`(渲染)/ `mboxes/`(每轮线程快照)/ `reviews/`(LLM
  分析产物,校验后并入)/ `cover/` / `final/`
- 发送者三分类(`config/reviewers.yaml`,可扩):
  **bot**(kernel test robot/syzbot,只提取事实)、**ai_reviewer**
  (`sashiko-bot@kernel.org`,默认不信任,逐条代码级反证)、**human**
  (maintainer 优先显示);系列作者自己的回复记为 author,不进待办

## 部署

```bash
cd /mnt/shared/openeuler/shared/AI提效/9.AutoFixForUpstream && bash install.sh
# 重启 Claude Code session(注册 /autofix-upstream skill)
```

部署到 `~/autofix-upstream`(PROJECT_ROOT);源码在 /mnt/shared,本地运行
解 SSHFS 慢盘。install 绝不触碰第三方 skill。

## 五个命令(在内核仓库目录下)

| 命令 | 作用 |
|---|---|
| `/autofix-upstream import` | 注册进行中的系列(分支/fix 已存在;HDBSS 首实例即此模式) |
| `/autofix-upstream init` | 新系列:b4 拉上一版 → 基于 master 建分支 → **调 patch-merge-workflow 合入(quick yaml 语义)** → cover 脚手架 → round-0 |
| `/autofix-upstream poll` | 手动拉一次增量(半自动模式下定时由 poll-loop 代劳) |
| `/autofix-upstream triage` | 交互式深度分析待处理意见(ai_reviewer 逐条反证) |
| `/autofix-upstream fix` | 按 analyzed+valid 意见改码:`commit --fixup` → 编译 → amend(仅自建 fixup) |
| `/autofix-upstream status` | 状态总览(只读) |
| `/autofix-upstream finalize` | 归档+备份分支 → fixup 挤回原 patch(映射表须确认) → cover 定稿 → format-patch 导出 |

## 半自动监控(本机 cron 不可用,用常驻循环)

```bash
# 清单:~/autofix-upstream/config/poll-series.list,每行 "<repo> <series-id>"
nohup setsid ~/autofix-upstream/bin/poll-loop.sh >> ~/autofix-upstream/poll.log 2>&1 &
# 停止: pkill -f poll-loop.sh ;机器重启后需手动拉起
```

单轮 `bin/poll.sh <repo> <series-id>`:
1. python 层拉取增量(b4 优先;lore 证书异常自动降级 `curl -k`;
   网络全挂可 `--mbox-file` 手动导入)
2. 有新意见 → **headless claude** 按 review-triage SKILL.md 分析
   (只写 reviews/,白名单+黑名单双约束)
3. `triage-merge` 校验合并(schema 违例拒绝)
4. 内核仓库脏检查(相对 import 基线;邮件正文按不可信输入对待)

**边界:自动流程只写文档,不改代码;`fix` 永远由人手动触发。**

## 关键设计

- **fix 信息不进原 patch message**:fix 用 `git commit --fixup`,finalize 由
  state 的 fix→patch 映射生成 rebase todo(不依赖主题匹配,导入的普通 fix
  commit 与新 fixup 一视同仁);orphans 守卫防 todo 漏写静默丢 commit;
  rebase 前自动归档 fix + 建备份分支;冲突自动 abort 可回退
- **cover 骨架+拼接**:`format-patch --cover-letter` 生成 shortlog/diffstat/
  base-commit 正确的骨架,harness 只拼接正文;v6 脚手架自动做链接重编号
  (新链接插为 [2],原 [2..N] 顺移)
- **LLM 产物隔离**:LLM 只写 `reviews/round-N/item-*.json`(schema 子集),
  `triage.json` 永远只有 harness 一个写者

## 已知限制

- lore 搜索页有反爬虫(Anubis),Message-ID 需用户提供或从发件箱复制
- 发信不在范围内(git send-email 未配置,导出后人工发送)
- master 前移:v1 只警告 + `harness.cli resync`,不自动 rebase
- rpm 上板验证:配置项已留(`rpm_validate.enabled`),默认关闭

## 自测

```bash
cd ~/autofix-upstream && python3 -m pytest tests/ -v
```
