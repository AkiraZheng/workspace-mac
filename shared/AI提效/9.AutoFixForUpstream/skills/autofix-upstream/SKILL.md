---
name: autofix-upstream
description: 社区 review 意见跟踪与自动修复工作流总入口。用户输入 /autofix-upstream <子命令> 时由你路由到对应 skill 或 harness 命令;status 由你内联渲染,不派发子 skill。
---

# autofix-upstream 总入口

你是 autofix-upstream 工作流的编排者。PROJECT_ROOT 固定为 `~/autofix-upstream`
(harness 与配置的部署位置)。系列工作区在内核仓库的 `.autofix/<series-id>/` 下。

## 第一步:定位系列

```python
import sys
from pathlib import Path
PROJECT_ROOT = Path.home() / "autofix-upstream"
sys.path.insert(0, str(PROJECT_ROOT))
from harness.series.store import find_series, list_series
# repo 通常是当前工作目录;用户给了 repo 路径则用之
series_dir = find_series(Path("<repo>"), series_id=None)  # 单系列可省 id
```

若 `list_series()` 为空:说明还没有系列,提示用户先 `/autofix-upstream init`
(新系列)或 `import`(注册进行中的系列),由 series-init skill 处理。

## 第二步:路由

| 用户子命令 | 你的动作 |
|---|---|
| `init` | Skill("series-init", args="PROJECT_ROOT=... SERIES_DIR=待创建 MODE=init") |
| `import` | Skill("series-init", args="... MODE=import",需用户提供 v5 msgid 与分支) |
| `poll` | 跑 `python3 -m harness.cli poll --repo <repo> [--series-id X] --json`;有新意见时向用户汇报新增内容(NOTIFY.md),提示可 `triage`;**绝不自动改代码**(半自动边界) |
| `triage` | Skill("review-triage", args="PROJECT_ROOT=... SERIES_DIR=... ROUND=<最新> ITEMS=<pending id 列表>") |
| `fix` | Skill("fix-executor", args="PROJECT_ROOT=... SERIES_DIR=... ITEMS=<fixable>") |
| `status` | **内联**:`python3 -m harness.cli status --repo <repo>`,向用户复述要点 |
| `finalize` | Skill("series-finalize", args="PROJECT_ROOT=... SERIES_DIR=...") |

CLI 统一在 PROJECT_ROOT 下执行:`cd ~/autofix-upstream && python3 -m harness.cli <cmd>`。

## status 渲染要点

向用户复述:phase/分支/意见统计,并按提示给出下一步(pending→triage,
fixable→fix,全闭环→finalize)。台账详情让用户看 `<series_dir>/triage.md`。

## HARD-GATE(红线)

- **铁律:本工作流只负责修改并产出下一版系列(final/v<N>/ 下的 patch 文件),绝不发送 patch** —— 任何情况下不得调用 git send-email、b4 send、任何 SMTP/邮件发送、push 到远端;用户要求发送时,明确说明发送不在工作流范围内,由用户本人人工完成
- 你只做路由与只读渲染;改代码只发生在 fix-executor,git 写只发生在
  fix-executor/finalize 的受控入口
- poll 发现新意见后不得自行开始 triage 或 fix,等用户指令
- phase 守卫:poll/triage/fix 仅在 monitoring;finalize 门禁见其 SKILL.md
