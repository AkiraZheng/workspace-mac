---
name: series-init
description: 新系列初始化或进行中系列注册。由 autofix-upstream 在 init/import 子命令时调用;init 模式负责 b4 拉取、建分支、调 patch-merge-workflow 合入上一版、cover 脚手架;import 模式只读注册现有分支。
---

# series-init — 系列初始化 / 导入

输入:`PROJECT_ROOT` `MODE=init|import` 以及模式专属参数(见下)。

## MODE=import(注册进行中的系列,分支与 fix 都已存在)

1. 从用户处确认:repo、work_branch、v5 cover 的 lore Message-ID、
   fix commit -> 目标 patch 的映射(用户给,或你读 fix diff 与各 patch diff 的
   文件/hunk 重叠推断后**展示给用户确认**)。
2. 把参数写入 series.yaml(模板:PROJECT_ROOT/config/series-templates/,
   repo/work_branch/prev_msgid/base_commit/series_authors 等字段)。
3. 执行:
   ```bash
   cd <PROJECT_ROOT> && python3 -m harness.cli import --config <series.yaml> \
     --fix <sha>=<seq> ... [--mbox-file <离线mbox>]
   ```
   CLI 会:校验分支拓扑(master..HEAD == N 系列 + M fix)、拉取线程做 round-0
   快照、配对 msgid、生成台账 stub、脚手架 cover 草稿。失败信息直接转述用户。
4. 向用户汇报导入摘要(status 输出),提示 `/autofix-upstream triage`。

**HARD-GATE:import 全程零 git 写操作**(不 checkout/commit/branch);
必须先由用户自己 checkout 到工作分支,CLI 校验不符会拒绝。

**铁律:本工作流只产出下一版系列文件,绝不发送 patch**(禁止 git
send-email、b4 send、SMTP、push;发送由用户人工完成,详见总入口)。

## MODE=init(新系列,v6 之后的 v7 或其它特性)

1. 收集参数(优先级:用户 prompt > series.yaml 模板 > 逐项询问):
   repo、series_id、上一版 lore msgid、上一版版本号、工作分支名(含 v<N+1>)、
   编译命令(默认 `make ARCH=arm64 -j4`)。
2. 拉取上一版 patch 系列(b4 am,证书异常时 harness 自动降级 curl -k,
   或用户给 --mbox-file 离线文件):
   ```python
   from harness.lore.b4fetch import fetch_thread, lore_url
   # fetch_thread(msgid, out_path) 返回使用的模式(b4/curl)
   ```
   patch 提取无需 b4 am:线程 mbox 里每封 patch 邮件即一个 patch 文件,
   由 patch-merge-workflow 的 mailsplit 处理。
3. git 操作(仅限以下三样,这是 init 唯一允许的 git 写):
   ```bash
   git -C <repo> checkout master && git -C <repo> pull   # pull 失败仅警告,用本地 master
   git -C <repo> checkout -b <work_branch> master
   ```
4. **调用 patch-merge-workflow 合入上一版(唯一合入通道,禁止裸跑 git am)**:
   Skill("patch-merge-workflow", args=
   "帮我把 <series_dir>/mboxes/round-0000.mbox 合入到 <repo> 的 <work_branch> 分支,"
   "继续用这个分支,不要新建,用 make ARCH=arm64 -j4 编译")
   — prompt 直参使其走 branch_mode=existing + final_only 编译(quick 语义)。
   注意传**线程 mbox 中只含 patch 的部分**时,先用 harness 过滤:
   ```python
   from harness.lore.thread import split_mbox
   msgs = split_mbox(mbox, out_dir)
   patches = [m for m in msgs if m.is_patch and not m.is_cover]
   # 逐封写为 mboxes/v5/NNNN-<seq>.eml,把该目录交给 patch-merge-workflow
   ```
   冲突/编译失败由 patch-merge-workflow 的 conflict-handler/build-validator 处理,
   人工票(handoff_ticket)出现时转述用户。
5. 合入成功后执行(读分支记 series_commits、round-0 快照、cover 脚手架):
   ```bash
   cd <PROJECT_ROOT> && python3 -m harness.cli import --config <series.yaml> [--fix ...]
   ```
   (init 场景没有 fix 要登记,--fix 省略;分支已由你建好,CLI 的拓扑校验
   会通过,round-0 快照此时增量补齐。)
6. 汇报 + 提示 triage。

## 通用注意

- b4 am 默认会从线程收集 Acked-by/Reviewed-by 加进 patch —— 本工作流要求
  干净基底,series.yaml 已设 `b4.no_add_trailers: true`,不要改动。
- lore Message-ID 找不到时:请用户从发件箱复制,或用 WebFetch 搜
  lore.kernel.org(搜索页有反爬虫,优先让用户提供)。
