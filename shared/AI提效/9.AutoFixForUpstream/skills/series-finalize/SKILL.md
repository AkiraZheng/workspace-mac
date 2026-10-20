---
name: series-finalize
description: 意见稳定后的收尾:fix 挤回原始 patch、cover 定稿、导出 v6 系列。由 autofix-upstream 在 finalize 子命令时调用;rebase 前必须经用户确认映射表,全程有归档与备份分支兜底。
---

# series-finalize — 合入与产出下一版

输入:`PROJECT_ROOT` `SERIES_DIR`。

## 门禁(全部通过才继续,否则向用户说明并终止)

```bash
cd <PROJECT_ROOT> && python3 -m harness.cli status --repo <repo>   # phase=monitoring
git -C <repo> status --porcelain                                   # 必须为空
```
- 台账未闭环项(valid 未 fixed 的)逐项向用户确认:wontfix / deferred /
  现在补 fix;确有遗留可经用户明确同意后继续
- 建议(非强制)先在副本分支演练:`git branch <series>-dryrun` 后在该分支跑

## 第 1 步:cover 定稿(LLM 工作)

读 `<SERIES_DIR>/cover/cover-v<N+1>.draft.md`(脚手架)与台账,产出
`cover/cover-v<N+1>.final.md`:

1. **changelog 节**(替换 `<!-- CHANGELOG_PLACEHOLDER -->`):从台账
   valid+fixed 的 item 生成英文条目 —— kernel 惯例动词开头
   (Add/Fix/Move/Reword/...),按 patch 归组,重述而非直译中文;
   deferred/wontfix 中用户决定说明的,加 "Deferred:" 或说明段
2. **实现描述**:读各 patch 相对上一版的最终 diff,只有语义变化处才调整
   描述(保守:结构/顺序/行为变了才动,错别字级不动)
3. 链接区/SoB 保持脚手架;`message_change_needed` 的 patch,把
   `message_change_text` 定稿为独立文件 `final/reword-seq<N>.msg`
   (完整 commit message,含原 SoB 尾注)
4. 文件首行 `Subject: [PATCH v<N+1> 00/MM] <标题>`,空行后正文

## 第 2 步:rebase 计划(必须给用户确认)

```bash
cd <PROJECT_ROOT> && python3 -m harness.cli rebase-plan --repo <repo> \
  [--msg-file <seq>=final/reword-seq<N>.msg ...]
```
把打印的 **fix->patch 映射表与 todo** 展示给用户,明确确认后执行下一步。
映射有误时:修 series.yaml/state(`fix-associate` 或手改 state.json 的
fix_commits)后重新 plan。

## 第 3 步:执行 rebase

```bash
cd <PROJECT_ROOT> && python3 -m harness.cli rebase-run --repo <repo> \
  [--msg-file <seq>=final/reword-seq<N>.msg ...]
```
harness 自动:fix 归档(final/fixup-archive-*/)、备份分支
(backup/<series>-<ts>)、orphans 守卫、非交互 rebase、sha 重映射。
**失败会自动 abort 回 rebase 前** —— 转述错误给用户:通常是 fix 与后续
patch 冲突(映射错或 fix 需拆分),人工处理后再试。

## 第 4 步:导出

```bash
cd <PROJECT_ROOT> && python3 -m harness.cli export --repo <repo>
```
产出 `<SERIES_DIR>/final/v<N+1>/0000-*.patch + 0001..MM`。
复核(你自己做):cover 的 diffstat 与 shortlog 是否合理、changelog 是否
含全部 fix、**各 patch message 未混入 fix 信息**、`git log --oneline` 数量
正确。建议用户跑 `./scripts/checkpatch.pl` 复核。

## 第 5 步:收尾汇报

- 产物路径、备份分支名、fix 归档路径
- master 前移提醒:`git -C <repo> rev-parse master` != base 时建议先
  `git rebase --onto master <旧base>` + `harness.cli resync`,再重跑导出
- v6 发出后若继续跟踪新意见,用新的 msgid 重新 init 下一轮 —— 注意这只描述
  用户后续自己要做的事;**工作流本身到此为止,不做任何发送动作**

## HARD-GATE(红线)

- **铁律:finalize 的终点是 `final/v<N>/` 下的文件,绝不发送** —— 禁止
  git send-email、b4 send、任何 SMTP/邮件发送、push;即使用户明确要求
  "把 patch 发出去",也只回复"发送在工作流范围外,请人工完成"并停止
- rebase-run 之前必须完成:门禁检查 + 用户对映射表的确认
- 原始 patch 的 commit message 默认不动;仅 message_change_needed 且
  用户过目的才改
- 全程不删除备份分支与 fix 归档
