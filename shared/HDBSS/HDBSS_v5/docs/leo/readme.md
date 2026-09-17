# Leo DBM 系列分析（docs/leo/）

分析对象：Leonardo Bras `[RFC 0/5] KVM: arm64: New PTE dirty-page encoding, HAFDBS new usage`（2026-09-01），
已合入本仓库（基线 a500db7819c5 之上）：

| # | commit | 主题 |
|---|---|---|
| 1 | abf089b02d3c | pgtables: Change write bit from S2AP_W to DBM |
| 2 | cc87c84b71bb | Add KVM_PGTABLE_PROT_DIRTY |
| 3 | 14ef2b2dba5a | Introduce a dedicated walker for stage2 write-protect |
| 4 | 6ddad18d396a | Add KVM_REQ_RELOAD_STAGE2 |
| 5 | 96edd67e5e49 | Enable HAFDBS for guests not on migration |

## 社区就绪分支：code_v5_3_community

`[PATCH v5 00/13]` 系列已整理完毕并导出到 `HDBSS_v5/code_v5_3_community/`（0000-0013 共 14 个
文件，含 cover letter）。系列结构：

| # | 内容 | 形态 |
|---|---|---|
| 1-3 | Leo patch 1-3 | adapted pickup：`[zhengtian: ...]` 注记 + Link + 双 SoB（p1 折入嵌套洞修复、p2 折入 folio 拆账） |
| 4 | Leo patch 4 | 规范 pickup（Link + 双 SoB） |
| 5 | harvest（folio 收割） | Tian；注释已去 HDBSS 前向引用 |
| 6-10 | HDBSS cap/buffer/flush/ring-hook/ring-reserve | 原样（Tian/Eillon 作者与 SoB） |
| 11 | Derive the VM hardware dirty mode | Tian；压扁 Leo p5+F1/F3/F4+R1+auto-enable，Rework-of + Link 致谢 |
| 12-13 | ioctl + docs | 原样 |

验证状态：checkpatch 13/13 零 ERROR（仅新文件 MAINTAINERS 误报 WARNING）；
编译检查点（位置 4/5/11/HEAD）全过；树等价（vs code_v5_3_leo 仅 nested.c 3 行修复增量）；
干净 worktree `git am` 全系列通过且树一致；message 无 Unicode、无 stale SHA、主题行 ≤72 字符。
基线：a500db7819c5（base-commit 已写入 cover letter）。

## 文档索引

### dbm_blindspots_and_risks.md —— 主文档：系列全景分析

- §0 三态模型（N/WC/WD）与新契约（W↔DBM，DIRTY↔S2AP_W），"两种脏"（folio 记账 vs bitmap）
- §1-§4 四块子系统展开：嵌套虚拟化（三张 S2 表、bit51 安全洞、L2 支持边界）、设备页/ioremap（为何恒 WD）、gmem、pKVM（PROT_RW 补 DIRTY 的硬性要求、nVHE 零影响证明）
- §5 SMMU 侧影响：HTTU/DBM 同构机制、今天零影响的根据（无 S2 共享）、未来共享的风险窗口与前置约束、SVA 先例
- §6 与 HDBSS v5 的 rebase 冲突清单（逐 commit 决策）
- §7 风险清单 7 项（folio 记账缺口、HD 无 HA、VGA 性能悬崖、vtcr 竞态、TLBI、walker 并发原语降级等）
- §8 sashiko 问题处置总表 / §9 疑问快答表 / 附录：关键代码索引

### stage1_dbm_reference.md —— stage-1 ↔ stage-2 对照库

Linux stage-1 在生产环境以"WC 模式"跑了多年，我们缺的部件 stage-1 几乎都有样板：

- §0 位分配/三态双表对照（S1 双轨脏位 vs S2 单轨 + bitmap）
- §1 五件套 pte 函数（`pte_wrprotect` 先收割再收权、`pte_mkwrite` 未脏即停 WC）
- §2 四条链：写 fault 兜底（`pte_mkdirty` 一行放行）、读 fault 投机（动态看 folio 脏否）、unmap 收割（`zap_present_folio_ptes`:1780）、HD 使能（HA 先行 + 必配 TLBI）
- §3 八项对照总表：2 项已等价、3 项有样板可搬、1 项否决（SW 缓存位）

### hdbss_v5_unmap_harvest.md —— 设计增补：unmap 脏收割

风险清单 §7.1（folio 记账缺口）的长期修复方案：

- 约束与解法：pgtable.c 双编译 → `mm_ops->mark_harvested_page_dirty` 新回调，只给 guest pgt 接线
- walker 收割点 + host 实现（`pfn_valid` + `kvm_is_ad_tracked_page` 双 gate）+ 锁序/过标/粒度三个安全论据
- drain 不做 folio 收割（冗余性分析：F2+wp+unmap 已闭环，flush 保持纯 SRCU 原设计）
- SW2/SW3 借位否决结论 + 两个 patch 的实施清单

### hafbs_only_path_verification.md —— 非 HDBSS 路径正确性验证

Leo 系列在无 HDBSS 机器上的完整生命周期验证（四阶段状态机 + 九个不变式清单）：

- §0 提问表述的两处精确化（HD 关闭不改 PTE；标脏三段分工：信号/账本/放权）
- §1 四阶段时序：非迁移(WC/WD 混合) → 迁移开始(HD off + wp) → 迭代期(WC≡RO 经典流程) → 结束(无缝回 HD=1)
- §2 不变式 I1-I9 逐点验证（含 CLEAR 协议、S1PTW、wp/relax 锁互斥）
- §3 原系列 5 个伴生缺陷与 F1-F4/R1 修复的对应（VGA 悬崖恰在此路径）
- §4 设计优雅之处（WC 双重性格、wp skip、S1PTW 红利、零过渡成本）
- §5 关闭 R1c：mark_page_dirty_in_slot 隐式过滤非 logging slot

### leo_review_reply_draft.md —— 给 Leo 的问题清单（中文工作稿）

Leo 系列全部待沟通问题的中文分析（看懂后自行翻译成英文回复 lkml 线程）：

- §0 总览表：15 项问题 + sashiko 其余条目对账，来源/回应/处置三列标注（sashiko 重复项显式标记）
- §0.5 maintainer 意见对账（9/16）+ §0.6 一页总览表（9/17）："问题 patch/代码 → 问题所在 → 解决方法"三列对照表，已吸收 9/16–17 增量邮件（Leo 同意 combined series、Oliver 定性 micro-optimization、Leo 认领性能测试/问 pKVM）与 code_v5_3_community 的 0014 修复
- 第一部分（5 项，Leo 已回应）：folio 两种脏账（sashiko 5 连问完整复盘，含 Leo 逐条回应与对错评价）、HD 缺 HA、TLBI、静态判断（VGA 悬崖）、vtcr 竞态——每条带我们的修复 commit 与拟问 Leo 的一句话
- 第二部分（10 项新问题 N1-N10）：wrprotect 并发原语降级、硬件竞态静默化假设、vcpu_has_nv 粒度、always-on 设计、嵌套 bit51 短期处置、v2 边界协作、RELOAD 顺序文档化、性能数据、SMMU S2 共享前瞻、selftests——统一模板（问题/证据/影响/建议/拟问）
- 附录 A：英文邮件原稿（翻译时复用措辞）

### 回复leo-dbm-rfc.md —— 对外发送定稿（9/17）

三封可直接粘贴的英文邮件 + 可选跟帖 + 发送/发系列前清单（取代附录 A 邮件一，定稿邮件二）：

- 邮件 B（先发，回 Oliver + 问 Leo）：下周 HDBSS v5 随系列合并发布（dirty ring / dirty bitmap 两标脏场景已适配）；请求 p1-4 pickup + SoB、p5 改造为 derived dirty mode；性能数据分工（Leo 测 HAFDBS 形态，我们出 HDBSS 腿 + VGA 形态）
- 邮件 A v2（回 Leo 9/16 14:25）：简洁谦逊版——期待 Marc pointer（M.b 四处核查均无，一句带过）→ KVM 代码已限 L1 可见 HAFDBS 为 AF-only（nested.c:1781 limit_nv_id_reg()，commit d5bbb76f4474 为 Oliver 亲手封顶）→ 坦承对 NV 了解有限、保险起见先 revert 回 S2AP[1]-only → 等嵌套 HAFDBS 真实支持再回来（= 0001 已做，可移交 hunk）；D8.4.2.1 Table D8-76 移出正文留作弹药
- 邮件 C（随系列发，PATCH 2/5 线程）：技术细节 review 终版（#1-#5/N1/N2+N7/N9/N10），增量 = 衔接 B 的开头 + N2+N7 段补 0014 实证（RELOAD 只重载翻译寄存器、HDBSS buffer 寄存器陈旧丢脏）
- 邮件 D（可选，回 Leo 9/17）：pKVM 跟帖素材（HDBSSBR/HDBSSPROD EL2-only、hyp 侧管道、PROT_RW 补 DIRTY 后编码 pKVM 中性）
- §5 不发清单（bit51 条文出处让 Marc 回、N3/N4 暂停或归我们等）；§6 发送前工程清单（0014 squash 进 0007、清 Co-Authored-By、cover letter 重生成、复验）与性能数据兑现排期

## 相关材料（不在本文件夹）

- `docs/dbm_with_leo.md`：三态模型、编码/解码器、PERMS 掩码、wrprotect、HAFDBS 生命周期的逐函数分析（系列主链）
- `docs/sashiko_review_replies.md`：我们自己 HDBSS v4 系列的 sashiko 回复（与本文 §8 互补，勿混淆——那份是 v4 的，这份是 Leo 系列的）
- patch 源：`/mnt/shared/openeuler/shared/originPatch/HDBSS_V4/DBM_new_patch_by_leo/`（含 sashiko review 邮件与 Leo 回复全文）
