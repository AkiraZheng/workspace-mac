---
name: fix-executor
description: 按台账有效意见修改代码并生成 fix commit。由 autofix-upstream 在 fix 子命令时调用;最小修改、精确 add、commit --fixup、统一编译验证,amend 仅限本轮自建 fixup。
---

# fix-executor — 意见落地为 fix

输入:`PROJECT_ROOT` `SERIES_DIR` `ITEMS`(逗号分隔,缺省=analyzed+valid+
fix_type=code 且未 fixed 的全部 item)。

## 流程

**1. 逐 item 修复**(一次一个,顺序按 patch seq 升序,同 patch 的意见一起改):

- 读 `item.fix_approach_zh` 与目标 patch(`git show <series_commits[seq-1].sha>`)
- 遵循仓库编码风格(ARM KVM 见 arm-kvm-style skill 的惯例;注释密度与
  周边代码一致,不写废话注释)
- **最小修改**:只解决该意见指出的问题,不顺手重构
- 遇到与 patch 设计意图冲突的方案:停下来向用户说明,不擅自改变设计

**2. 提交**(每个 item 或每组同 patch 意见一个 commit):
```bash
git -C <repo> add <精确的文件列表>        # 禁止 add -A / add .
git -C <repo> commit --fixup=<目标系列commit sha>
```
fix commit message 用 `--fixup` 生成的 `fixup! <原主题>`(信息不进
message,由 cover changelog 承载;finalize 靠映射不靠主题匹配)。

**3. 统一编译验证**(全部 commit 完成后跑一次,4 核机器编译很贵):
```python
from harness.fix.build import run_build, tail_errors
res = run_build(store.cfg["build"]["command"], store.cfg["build"]["artifact"],
                Path("<SERIES_DIR>") / "build", store.repo)
```
- 成功(`res.ok`):继续
- 失败:读 `res.log_path` / `tail_errors()` 诊断,修复后 **校验 HEAD 是本轮
  自建 fixup**(`git log -1 --format=%s` 以 `fixup!` 开头)再
  `git commit --amend --no-edit`,重编;**最多 3 次**,仍失败则回退该 item
  状态为 analyzed 并向用户报告

**4. 登记**:
```bash
cd <PROJECT_ROOT> && python3 -m harness.cli fix-record --repo <repo> \
  --sha <fix sha> --target-seq <N> --origin <item id> --item <item id>
```
(修复跨多个 patch 时只登记主目标,并在台账 note 说明。)

**5. 可选上板验证**:`series.yaml` 的 `rpm_validate.enabled=true` 时按其
command 执行,失败不阻断(上板问题单独记录)。

**6. 汇报**:每个 item 的修复方式、commit sha、编译结果;然后建议用户
观察社区,待意见稳定后 `/autofix-upstream finalize`。

## HARD-GATE(红线)

- **铁律:本工作流只产出下一版系列文件,绝不发送 patch**(禁止 git
  send-email / b4 send / SMTP / push;用户要求发送时明确拒绝)
- **只允许 amend 本轮自己创建的 fixup commit**(必须校验 HEAD 主题),
  严禁 amend 系列 commit 本身
- 严禁 `git reset --hard` / rebase / checkout 其它分支
- 编译 3 次失败必须停下报告,不得无限制重试
- fix 信息不写入任何 commit message(由 cover changelog 承载)
