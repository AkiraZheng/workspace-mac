# HDBSS v5 正式发布系列交付记录(2026-09-20)

> **定位**:v5 发布系列的编排决策、验证证据与执行过程的完整存档。
> 系列基于 `code_v5_4_merge_DBM_HDBSS` 分支重排而来,发布分支为
> `hdbss-v5`(基线 `a500db7819c5`),交付物为 15 个 patch 文件
> (cover letter + 14 补丁),位于本目录 `v5_series/`。
> **状态:已就绪,未发送**——发送动作由作者本人执行。

## 一、系列终态(14 补丁)

| # | 补丁 | 作者 | 相对 v5_4 的变化 |
|---|------|------|------------------|
| 00 | cover letter | — | 新写(combined series 声明、三态模型、NV 三层语义、N5 声明、崩溃验证叙事、perf follow-up 承诺) |
| 01 | pgtables: Change write bit from S2AP_W to DBM | Leonardo Bras | 原样 |
| 02 | Add KVM_PGTABLE_PROT_DIRTY | Leonardo Bras | 原样 |
| 03 | Introduce a dedicated walker for stage2 write-protect | Leonardo Bras | **折入 AF 竞态注释**(重写 attr_walker 时丢失的文档,找回) |
| 04 | Add KVM_REQ_RELOAD_STAGE2 | Leonardo Bras | 原样 |
| 05 | Harvest stage-2 dirty state into the host folio account | Tian Zheng | **折入收割注释 + block-folio 说明**(措辞去 HDBSS 前向引用) |
| 06 | Add support for FEAT_HDBSS | Tian Zheng | 原样 |
| 07 | Add HDBSS per-vCPU buffer management | Eillon | **折入 BR 所有权编程**(e4f4ea4d:守卫 `hdbss_pg` + put 对称 + `__GFP_ZERO`,commit message 保留完整崩溃叙事) |
| 08 | Add HDBSS fault handling and buffer flush | Eillon | 原样 |
| 09 | Add kvm_arch_dirty_ring_size_updated() hook | Tian Zheng | 原样 |
| 10 | Reserve dirty ring space for the HDBSS buffer | Tian Zheng | 原样 |
| 11 | Derive the VM hardware dirty mode from dirty logging | Tian Zheng | **折入三件事**:NV gate 摘除 + `kvm_has_nv` 改名 + per-MMU `kvm_hw_dirty_enabled`(e963544);首-vCPU 守卫(7dea220);WRITE_ONCE 双竞态完整论证(8225880,放在 HD 激活处,前向引用全部消解) |
| 12 | Add HDBSS buffer size ioctl for dirty-bitmap mode | Tian Zheng | 原样 |
| 13 | Document HDBSS buffer size ioctl | Tian Zheng | 原样(api.rst 已含 dirty-ring 重置契约说明,无需补) |
| 14 | selftests: Add HDBSS buffer size ioctl interface test | AkiraZheng | **修两处后加入**:默认值 `SZ_4K`→`getpagesize()`(64K 内核可移植);补 "先设 size 再开 ring 被重置为默认" 契约用例 |

**被排除的内容**:日志 commit(`3613da7b6466` + 其修剪 `0c62e8b8be80`)——
按决策不随系列发出,保留在内部测试分支(`code_v5_4_merge_DBM_HDBSS`)。

**作者归属**(git 实测):Leonardo Bras 4 个(01-04)、Eillon 2 个(07-08)、
Tian Zheng 7 个、AkiraZheng 1 个(14)。各补丁 SoB 链完整(含折入内容的
原作者 SoB;Claude 的贡献以 `Co-developed-by` + SoB 对标注)。

## 二、验证矩阵

| 验证项 | 结果 | 说明 |
|--------|:---:|------|
| 逐补丁 bisectability(每 commit 单独 `make arch/arm64/kvm/`) | ✅ 14/14 | 01-10、12-14 由 `rebase -x` 直证;**11 为独立构建补证**(见下"教训") |
| checkpatch 全系列 | ✅ 0 error | 仅 2 个 "MAINTAINERS need updating?" 启发式警告(0007/0014 新文件在已有覆盖路径下,惯例忽略) |
| 树级等价性(vs `code_v5_4_merge_DBM_HDBSS` 终态) | ✅ | diff = 恰好被丢弃的日志内容(arm.c +5 / dirty_bit.c +7 / mmu.c +4)+ v5_4 没有的 selftest;`pgtable.c` 零 diff |
| `git am` round-trip(独立 worktree,基线上顺序 am) | ✅ 14/14 | 干净落位,无冲突 |
| selftest 编译 | ✅ 0 警告 | 含格式(%lld→unsigned long long cast)、行长(≤100)、比较方向(常量在右)全部修正 |
| 全链编译 | ✅ 0 error / 0 warning | 中途抓到并修掉两处:`free` 日志 `%u` 打 `unsigned long`(−Wformat);patch 11 畸形缩进行 |
| 真机 selftest | ⚠️ **未跑** | 本机无 `/dev/kvm`;**发前建议**在有 HDBSS 硬件的机器上跑一轮 `arm64/hdbss_test` 实机验证 ioctl 断言 |

> **教训(rebase -x 的坑)**:`git rebase -x 'make ... || exit 1'` 在 exec
> 失败时会**停在失败处**,之后手工 `git rebase --continue` **会跳过失败的
> exec 继续前进**,不会重跑。本系列曾因此出现"patch 11 验证通过"的假象
> (实际该补丁当时含有编译不过的内容),靠树级等价性 diff 才暴露。结论:
> rebase -x 中断后,必须检查 `.git/rebase-merge/done` 确认失败点,并对
> 该补丁单独补证,不能盲目 --continue。

## 三、过程中顺手修掉的问题

**继承自 v5_4、在重排时修复:**

1. walker 注释的三处**前向引用**(注释提到 HDBSS buffer/folio account,但
   所在位置早于这些机制的引入补丁)→ 按归属拆分重排:AF 注释→03、收割
   注释→05、大竞态论证→11(HD 激活处,引用全部消解);
2. selftest 硬编码 `HDBSS_DEFAULT_SIZE SZ_4K` → `getpagesize()`(16K/64K
   内核上默认值断言和 SZ_8K/SZ_16K 有效用例原本必挂);
3. selftest 缺 "set-then-ring 被重置为默认" 的契约用例(防止未来有人"好
   心"保留用户值而重新引入 ring soft_limit 下溢)→ 补上;
4. selftest 三处 `格式 %lld` 配 `u64`(arm64 上是 unsigned long)的
   -Wformat 警告 → `unsigned long long` cast。

**我自己在重排过程中引入、又当场修掉(记录以免复燃):**

5. patch 05 冲突合并时的双 `/*`(嵌套注释开头,编译不报错但格式错);
6. patch 11 冲突合并时的残留块(AF 注释 + 多余 `*/` + 重复收割调用)和
   畸形缩进行(`else if` 顶格 + 双 tab)——前者靠树级等价 diff 抓到,
   后者靠 checkpatch 抓到;
7. amend 时弄丢原作者 SoB(0007 的 Eillon、0014 的 AkiraZheng)→ 找回;
8. `Co-Authored-By: Claude` 非内核标准 → 全系列统一 `Co-developed-by:` +
   `Signed-off-by:` 对;
9. cover letter 的 diffstat/作者分布手工初稿有误 → 以 `git diff --stat`
   和 `git log --format` 实测数据校正。

## 四、坦白交代

1. **误弹了一个旧 stash**:在分支操作中 `git stash pop` 带出了上个
   session 的遗留 stash(内容:在 `check_vcpu_requests` 里给
   KVM_REQ_RELOAD_STAGE2 加 handler 的位置实验)。评估:树上 patch 04
   已有正式版本,stash 内容与之重复,**无独有数据损失**;stash 条目已被
   pop 消费,原对象悬挂在库中,gc 之前理论上可用 `git fsck --unreachable`
   找回(本机 fsck 过慢未执行)。
2. **发前未完成项**:真机 selftest(见验证矩阵 ⚠️ 行);NV 虚拟机回归
   (L1/L2 各自启动 + L2 内存读写——patch 11 是唯一语义变化点,已在
   `code_v5_4` 上做过代码级论证,实机回归建议随 selftest 一并跑)。

## 五、发送建议(由作者执行)

- **收件人**:`kvmarm@lists.linux.dev`、`linux-arm-kernel@lists.infradead.org`
- **Cc**:Marc Zyngier <maz@kernel.org>、Oliver Upton <oliver.upton@linux.dev>、
  Leonardo Bras <leobras@redhat.com>(以及在 [1] 线程中参与过评审的成员)
- **主题**:`[PATCH v5 00/14] KVM: arm64: FEAT_HDBSS support for stage-2 dirty tracking`
- **发送方式**:`git send-email --to=... --cc=... v5_series/*.patch`
  (0000 是 cover letter,一并发送)
- **cover letter 已内置**的三个主动征求意见点(引导评审注意力):
  1. patch 7 的所有权式 HDBSS 寄存器编程 vs 各 VTCR 翻转点分别编程;
  2. HAFDBS 不设 NV gate 而 HDBSS 暂设(patch 11);
  3. per-MMU `kvm_hw_dirty_enabled()` 谓词(嵌套 shadow 安装保持
     writable-dirty,L2 行为零变化)。
- **发前动作清单**:
  - [ ] 真机跑 `arm64/hdbss_test`
  - [ ] NV 虚拟机回归(L1/L2 启动 + L2 读写)
  - [ ] 确认 rebase 基线:系列基于 `a500db7819c5`(9 月初 mainline merge
    点);若发出时上游已推进,建议 rebase 到当时最新 kvmarm 基线后重新
    生成 patch
- **参照线程**:[1] https://lore.kernel.org/all/20260901171558.2674031-1-leo.bras@arm.com/

---

*本记录由 v5 发布编排过程自动整理;验证证据均可由 `hdbss-v5` 分支
(a500db7819c5..8b89e00f689e)与 `v5_series/` 目录复现。*
