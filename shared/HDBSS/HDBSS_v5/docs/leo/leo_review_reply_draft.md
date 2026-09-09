# 给 Leo 的 DBM 系列问题清单（中文工作稿）

> **定位**：Leo `[RFC 0/5]` 系列全部待沟通问题的中文分析稿。每条讲透"问题是什么、证据在哪、
> 什么场景会坏、我们建议怎么改"，看懂后自行翻译成英文回复 lkml 线程。
> **与 sashiko 的关系**：凡是与 sashiko AI review 重复的问题，均显式标注（来源列 +
> 正文"与 sashiko 的关系"小节），sashiko 原文和 Leo 的英文回应保留原样并附中文翻译。
> **修复状态**：`[已修 xxx]` = code_v5_3_leo 分支已带该修复（commit 号可查）；
> `[待问]` = 需 Leo 澄清；`[讨论]` = 设计向，看 Leo 意愿。

## 0. 总览表

| # | 问题 | 来源 | Leo 回应 | 处置 |
|---|---|---|---|---|
| 1 | folio 两种脏账（fault 路径标脏被改成 DIRTY 门控） | **sashiko Critical ×5 连问** | 认了最后一条（good catch），前四条答偏/误报 | [已修 F2 + harvest] |
| 2 | HD 不带 HA（疑似规格违规） | 自查（sashiko 未报） | **无回应** | [已修 F1] |
| 3 | 翻 HD 无 TLBI | **sashiko High** | 半辩护（只答了开 logging 方向） | [已修 F3] |
| 4 | compute_prot 静态能力判断（VGA 悬崖） | **sashiko High** | 认了 tradeoff 但低估普遍性 | [已修 F4] |
| 5 | vtcr 无锁 RMW 竞态 | **sashiko Critical** | 认了方向（加 slots_lock），未验证死锁 | [已修 R1 推导式状态机] |
| N1 | wrprotect walker 并发原语降级（cmpxchg→裸写） | 自查 | 无（sashiko 也没报） | [待问] |
| N2 | WRITE_ONCE 与硬件原子更新竞态——静默化假设零注释 | 自查 | 无 | [待问] |
| N3 | vcpu_has_nv 从 per-vcpu 改 per-KVM 粒度 | 自查 | 无 | [待问] |
| N4 | HAFDBS always-on 还是 opt-in | 自查（设计） | 无 | [讨论] |
| N5 | 嵌套联合判断短期处置（bit51 安全洞） | **sashiko High 的后续** | 声明依赖 Oliver 模拟系列，未改代码 | [待问] |
| N6 | v2 边界：我们的 fixup 他收不收 | 自查（协作） | 间接（patch 4 线程说过 "rebase as much as you want"） | [待问] |
| N7 | RELOAD-before-wp 顺序依赖文档化 | 自查（**支撑 sashiko TLBI 条的开向论证**） | 无 | [待问] |
| N8 | 非迁移 HAFDBS 性能数据 | **sashiko High（性能条）的后续** | 承认没数据（"really just want feedback"） | [讨论] |
| N9 | SMMU 共享 S2 前瞻：WC 页对无 HTTU SMMU 是 RO | 自查 | 无 | [讨论] |
| N10 | 三态编码的 selftests 计划 | 自查 | 无 | [讨论] |

### 补充：sashiko 其余条目（不成节，仅对账）

| sashiko 条目 | Leo 回应 | 结论 |
|---|---|---|
| patch2 Q1：编码器 WC = "DBM bypass" | "That's the desired effect" | **误报**，WC 是设计本意 |
| patch2 Q2/Q3/Q4：gmem/compute_prot/dirty 变量三连问 | "disable HAFDBS or enable HDBSS" / "That's the desired behavior" / "read fault does not dirty a folio" | **答偏**——混淆两种账（详见第一部分 §1），是 #1 的铺垫而非独立问题 |
| patch5 [Low]：KVM_MR_DELETE 死代码 | "we should be safe" | pre-existing，无害，顺手清理即可 |

---

## 第一部分：Leo 已回应的问题

### 1. folio 两种脏账——sashiko 5 连问的完整复盘

**与 sashiko 的关系**：本条 = sashiko patch 2 的全部 5 个 Critical（同一主题五连问），
是整个系列最重的问题。

**问题核心**：Leo patch 2 把 fault 路径的两处"标脏"都挂到了 `prot & KVM_PGTABLE_PROT_DIRTY` 上：

```c
/* arch/arm64/kvm/mmu.c, kvm_s2_fault_map() */
	bool dirty = prot & KVM_PGTABLE_PROT_DIRTY;
	...
	kvm_release_faultin_page(kvm, s2vi->page, !!ret, dirty);  /* ① host folio 账 */
	...
	if (dirty && !ret)
		mark_page_dirty_in_slot(...);                         /* ② KVM bitmap 账 */
```

但这两本是**精度要求相反的账**：
- **folio 账**（`SetPageDirty`，回收/写回正确性）：必须**投机**——凡"可能被免锁写脏"的映射，
  fault 时就得标。`kvm_release_faultin_page` 现有注释原文就是这份合同："KVM must (somewhat)
  speculatively mark the folio dirty if KVM could locklessly make the SPTE writable"，x86 靠
  同一条活着（x86 硬件脏位同样免 VM exit）。
- **bitmap 账**（迁移增量拷贝）：必须**精确**——读 fault 的 WC 页进位图 = 预拷贝白运干净页。

**丢数据场景**（sashiko 原文场景，完整链条）：

```
host 页曾 swap-out 又 swap-in → folio "干净"（内容与 swap slot 旧内容一致）
→ guest 读 fault 建 WC → release clean（读 fault 无 DIRTY）
→ guest 写 WC → 硬件免 fault 升 WD（零 VM exit，KVM 无感知）
→ 内存压力回收：folio 干净 → 直接丢页不写回
→ guest 再访问 → swap 回来的是旧数据 → 静默数据损坏
```

**sashiko 5 连问与 Leo 逐条回应**（完整对账）：

| 问 | sashiko 问的 | Leo 英文原话 | 中文翻译 | 评价 |
|---|---|---|---|---|
| Q1 | 编码器产出 (DBM=1, S2AP_W=0) 是不是 "DBM bypass" | "That's the desired effect, as we can use HAFDBS/HDBSS to automatically update and track them." | 这正是期望的效果，我们可以用 HAFDBS/HDBSS 自动更新和跟踪 | **误报**，WC 是本意 |
| Q2 | gmem 的 folio 记账会不会在 HAFDBS 下丢 | "Yes, that's why for dirty-tracking host should either disable HAFDBS or enable HDBSS if available." | 会，所以做脏跟踪时 host 要么关 HAFDBS 要么开 HDBSS | **答偏**：关 HD/开 HDBSS 解决的是迁移账，救不了回收账——非迁移 VM 没有 bitmap 也需要 folio 账 |
| Q3 | 读 fault 留 WC，硬件后续免锁写脏 KVM 不知道？ | "That's the desired behavior. If we need tracking, see above comment." | 这就是期望行为，要跟踪见上条 | 同上混淆 |
| Q4 | dirty 变量派生，host MM 把 folio 记干净？ | "Yes. The main idea is that a read fault does not dirty a folio, just as it already happens when dirty-tracking is enabled." | 对，读 fault 本来就不该把 folio 标脏，logging 期一直如此 | **半对**：对 bitmap 成立（精确），对 folio 不成立（必须投机）——拿 logging 期 bitmap 语义套了 folio 语义 |
| Q5 | release clean + 硬件置 S2AP_W 无 exit + unmap 不收割 → 回收丢数据？ | "Ah, good catch. IIUC: [CPU0/CPU1 竞态图] ... I think it would be better to use writable instead of clean, as IIUC there should be no issue marking a clean page as dirty other than a bit of overhead on calling kvm_set_page_dirty(). Does it work?" | 抓得好，画了竞态图；我认为改成用 writable 比用 clean 好，把干净页标脏除了多调一次 kvm_set_page_dirty 没别的问题。这样行吗？ | **唯一答对的一条**：提出的修法正确（= 我们的 F2），但**只修了 fault 端**——unmap/wp 收割端他没意识到（stage-1 的 zap_present_folio_ptes 样板） |

**我们的修复**：F2（a7947d2ff031）拆账——release 用 `prot & PROT_W`（投机），bitmap 保持
DIRTY（精确）；harvest（8fc9342022ca）补收割端——wp 清位前、unmap 拆映射前把 S2AP_W
折算回 folio（stage-1 zap 样板）。drain 侧经冗余性分析放弃。

**拟问 Leo**（Q5 的跟进）："你提的 use writable 我们已验证并合入（拆成 folio 用 W、bitmap
用 DIRTY 两本账）；另外补了 wp/unmap 两处收割（对齐 stage-1 的 zap_present_folio_ptes），
fault 端 + 收割端合起来才闭环——unmap 侧你考虑过吗？"

### 2. HD 不带 HA（疑似规格违规）

**与 sashiko 的关系**：自查，sashiko 未报，Leo 无任何回应。

**问题**：patch 5 只设 `kvm->arch.mmu.vtcr |= VTCR_EL2_HD`，HA 恒为 0。三重反证：

1. SMMU 驱动同场景（walk 的表可写位就是 DBM 位）永远成对开，注释原文：
   "To enable dirty flag update, set both Access flag and dirty state update"
   （arm-smmu-v3.c:1676）；SVA CD 也是 `CD.TCR.HA|HD` 一起（arm-smmu-v3-sva.c:108，
   "PTE_WRITE and PTE_DBM share the same bit"）。
2. 内核自家 stage-1：proc.S `__cpu_setup` 先开 HA，HD 经 `ARM64_HW_DBM` cap 延迟补开
   （cpufeature.c `cpu_enable_hw_dbm`），从未出现单开 HD 的写法。
3. FEAT_HDBSS 规格要求 VTCR_EL2.{HDBSS,HA,HD} **全 1** 才生效（D8.5.2.3）——HDBSS 系列的地基。

**影响**：轻则 HD 不生效（优化失效但行为安全，写照常 fault），重则 CONSTRAINED
UNPREDICTABLE。需对着 ARM ARM VTCR_EL2.HD 的 field description 定案。

**我们的修复**：F1（e9449e94cc9d），两处入口（setup_vcpu / set_hafdbs→状态机）都改为
`HD | HA` 成对。附带收益：mmu-notifier 老化页的 AF fault exit 消失。

**拟问 Leo**："除非 ARM ARM 说 VTCR_EL2.HD 对 HA 没有依赖，否则建议 `HD | HA` 成对设；
你们内部有没有核对过这条 field 约束？"

### 3. 翻 HD 无 TLBI

**与 sashiko 的关系**：sashiko patch 5 的 High 条，Leo 半辩护。

**sashiko 原文**：VTCR 属于可被 TLB/context cache 缓存的翻译体系寄存器，改它需要 VMID 级
TLB 无效化，否则 CPU 可能继续用 HD=1 时代的缓存翻译静默绕过写保护。

**Leo 回应**："This is called when we enable dirty-tracking, and the next steps after that
will be to clean the dirty-bits and then do a TLBi, so it should be fine for that scenario.
Maybe I should add a comment to explain the caller is responsible to carry a TLBi."
（这发生在开脏跟踪时，后续步骤会清脏位然后做 TLBi，所以那个场景没问题。也许我该加注释
说明调用方负责 TLBI。）

**我们的分析**（方向性拆解）：
- **开 logging 方向（HD 1→0）**：Leo 说的对——后续 `kvm_mmu_wp_memory_region()` 末尾的
  `kvm_flush_remote_tlbs_memslot()` 兜底；且翻转窗口内的写在迁移协议上属于"快照前写入"，
  由初始全量拷贝覆盖。**功能安全，但顺序依赖是隐式的**（没人写注释）。
- **关 logging 方向（HD 0→1）**：他没答。旧 TLB 缓存着 WC 页的 RO 翻译（HD=0 时代 walk 出
  的），继续拦写 → 每页再付一次 fault 才回到免 fault 世外桃源。**功能无害，收益打折**。
- **样板**：内核自家 `cpu_enable_hw_dbm()` 翻 TCR_EL1.HD 配 `isb() + local_flush_tlb_all()`——
  连这个先例都没跟。

**我们的修复**：F3（1bce58b422e1），模式翻转后 `kvm_flush_remote_tlbs(kvm)`
（`__kvm_tlb_flush_vmid` 是 inner-shareable 广播，单 CPU 执行即可）。

**拟问 Leo**："开方向靠后续 wp 的 flush 兜底我们认可，但这个顺序依赖能否注释固化？关方向
（HD 回 1）的旧 RO 缓存翻译问题你怎么看？内核 stage-1 的 cpu_enable_hw_dbm 是翻 HD 配
local_flush_tlb_all 的。"

### 4. compute_prot 静态能力判断（VGA 悬崖）

**与 sashiko 的关系**：sashiko patch 5 的 High 条（性能），Leo 认了 tradeoff 但低估普遍性；
且 sashiko/Leo 都没发现更深一层的"静态判断"问题。

**sashiko 原文**：单个 memslot（如 VGA framebuffer）开 dirty logging → 全局关 HD →
非 logging slot 的已建 WC 页每次写都 Permission fault。

**Leo 回应**："Yes, that's an expected tradeoff. I believed it would be fine as the usecase
I had in mind for dirty-tracking was live migration, which usually tracks all memory at
once... If there is a common use case for tracking a single memory slot of regular memory,
then maybe this patch has to be reworked."（是预期折衷。我想的场景是热迁移，通常一次跟踪
全部内存……如果跟踪单个普通内存 slot 是常见用例，这 patch 可能得重做。）

**我们补的两层**：
1. **VGA 不是边角是常态**：QEMU std VGA 对 VRAM slot **常年**开 LOG_DIRTY_PAGES（显示刷新
   跟踪），带显示的桌面包 VM 全中。他以为的"特殊场景"恰是最常见的非迁移 VM。
2. **更深一层（sashiko 也没报）**：判断用的是**静态能力** `kvm_supports_hafdbs(kvm)`，
   HD 被全局关掉后它仍为 true → 非 logging slot 的**新读 fault 还是建 WC** → HD=0 下 WC=RO
   → 每页一 fault **持续发生**，不止存量页。stage-1 的同类投机（finish_fault）看的是
   `folio_test_dirty` 这个**动态事实**（mm/memory.c:5716）。

**讽刺点**：优化目标是"非迁移免 fault"，结果最常见的非迁移 VM（带 VGA）反而全体退化成
"每页一 fault"。

**我们的修复**：F4（f9404adb9b91），新增 `kvm_hw_dirty_enabled()`（读动态
`vtcr & VTCR_EL2_HD`）替换静态判断；竞态良性（最坏一页多 fault 或多标一次 folio）。

**拟问 Leo**："静态 cap 判断建议换成动态 HD 状态（VGA 常态 logging 下现在每页都白付一次
fault）；或者 set_hafdbs(0) 时把存量 WC 批量升 WD，你觉得哪个方向对？"

### 5. vtcr 无锁 RMW 竞态

**与 sashiko 的关系**：sashiko patch 5 的 Critical 条，Leo 认了方向但没做完。

**sashiko 原文**：`kvm_setup_vcpu`（持 config_lock）与 `kvm_set_hafdbs`（持 slots_lock）
对 `kvm->arch.mmu.vtcr` 交错 RMW；vCPU 创建与开 logging 并发时 HD 可能错误地留在 1 →
硬件静默置脏绕过软件标脏 → **迁移丢脏页**。

**Leo 回应**："I think that this may be a hard to hit scenario, but to be sure I think it
should not hurt to hold the slots lock here as well. Have to properly check if I won't
cause any kind of dead/live lock here, though."（难触发，但加把 slots_lock 稳妥；
得确认不会死锁/活锁。）

**我们的立场**：加锁是方向，但**更优解是把 HD 变成纯推导量**——
`cap && nr_memslots_dirty_logging == 0`，每次事件重算，RMW 覆盖窗口直接消失，不用调锁序。
已在 R1（87cb9c4a24f4）落地为三态状态机 `kvm_arch_update_hw_dirty_mode()`（OFF / HAFDBS /
HDBSS），顺带解决了 HDBSS enable/disable 与 set_hafdbs 方向相反的双重钩子问题。

**拟问 Leo**："与其给 setup_vcpu 加 slots_lock，我们改成了纯推导重算（三态状态机），
你觉得这个方向他 v2 会不会收？加锁方案你死锁查完了吗？"

---

## 第二部分：新问题

### N1. wrprotect walker 并发原语降级

**与 sashiko 的关系**：自查，sashiko 未报。

- **问题**：patch 3 的专属 `stage2_wrprotect_walker` 用裸 `WRITE_ONCE(*ctx->ptep, new)`，
  旧路径（`stage2_update_leaf_attrs` → `stage2_attr_walker` → `stage2_try_set_pte`）对
  SHARED walk 走 cmpxchg、竞争返回 -EAGAIN 重试。
- **证据**：hyp/pgtable.c `stage2_wrprotect_walker` vs `stage2_try_set_pte`（后者对
  `kvm_pgtable_walk_shared` 走 `cmpxchg(ctx->ptep, ctx->old, new)`）。
- **影响**：当前唯一调用方 `kvm_stage2_wp_range` 在 mmu 写锁下（`stage2_apply_range` 持锁），
  与 relax（读锁 + cmpxchg）读写锁互斥，**今天安全**。但 API 契约静默收紧——将来任何人在
  read lock + SHARED 语境调用 wp（比如 HDBSS drain 后批量重武装）就是丢失更新竞态。
- **建议**：要么 walker 恢复 cmpxchg + EAGAIN 重试，要么函数头注释声明 exclusive-only 契约。
- **拟问 Leo**："wrprotect 换成专属 walker 后丢掉了 SHARED walk 的 cmpxchg 保护——是有意
  收紧为 exclusive-only 吗？是的话建议注释写死，防止后人误用。"

### N2. WRITE_ONCE 与硬件原子更新竞态——静默化假设零注释

**与 sashiko 的关系**：自查（N1 的姊妹问题）。

- **问题**：HA/HD=1 时硬件对 PTE 做**原子 RMW**（置 AF / WC→WD 升 S2AP_W），软件 plain
  store 理论上可覆盖丢掉硬件更新。wp 期间硬件已被"模式翻转的 RELOAD(KVM_REQUEST_WAIT)
  返回后无 vCPU 在 guest"这个**静默化假设**保护，所以安全——但这个假设全代码零注释。
- **证据**：我们的验证文档 `hafbs_only_path_verification.md` 不变式 I2/I3 就是靠它成立的；
  旧 `stage2_attr_walker` 有同类注释先例（"We may race with the CPU trying to set the
  access flag here, but worst-case the access flag update gets lost"）。
- **影响**：丢 AF 可自愈（HA=1 下次访问硬件再置；HA=0 走 Access Flag fault），丢 S2AP_W
  升级同理自愈——**但读者不点破不敢信**，尤其将来有人在 HD=1 语境下新增软件清位路径时
  会直接踩雷。
- **拟问 Leo**："wp 的 WRITE_ONCE 之所以不跟硬件 DBM 更新竞态，靠的是'模式翻转先于 wp 静默
  所有 vCPU'这个顺序——这是有意设计的吗？能否在 walker 里注释固化？"

### N3. vcpu_has_nv 从 per-vcpu 改 per-KVM 粒度

**与 sashiko 的关系**：自查（patch 5 附带重构）。

- **问题**：patch 5 把 `vcpu_has_nv(vcpu)` 重构成 `kvm_vcpu_has_nv(kvm)`（per-KVM），语义
  从"这个 vcpu 有 EL2"变成"任一 vcpu 有 EL2 则全 VM 按 nv 算"。
- **影响**：对 HAFDBS gating 是**保守方向**（安全）；但 vcpu feature 混配的 VM（比如 3 个
  vcpu 只有 vcpu0 开 EL2）语义变了，且 `vcpu_has_nv` 在内核里还有大量其他调用点共享这个
  语义变化。
- **拟问 Leo**："这个粒度变化是 HAFDBS gating 需要还是顺手改的？混配 feature 的 VM 你预期
  是什么行为？"

### N4. HAFDBS always-on 还是 opt-in

**与 sashiko 的关系**：自查，设计向。

- **问题**：patch 5 对合格 VM（VHE + 非嵌套 + HW_DBM）**无条件**开 HAFDBS，无用户可见开关。
- **参考**：x86 的 PML 也是 always-on（有先例）；但 HAFDBS 改变的是 PTE 脏位语义而不仅是
  buffer，VMM 用其他脏跟踪手段时（如纯 VFIO dirty tracking）是否会被 surprise？
- **拟问 Leo**："有没有考虑过像 PML 一样直接 always-on，还是给 VMM 一个 opt-out 的
  capability？你心里的部署画像是什么？"

### N5. 嵌套联合判断的短期处置（bit51 安全洞）

**与 sashiko 的关系**：**sashiko patch 1 的 High 条的直接后续**。

- **sashiko 原文**：L0 把 L1 可见 HAFDBS 限制为 AF-only（nested.c:1783
  `ID_REG_LIMIT_FIELD_ENUM`），bit51 对 L1 是 RES0；诚实的 L1 拿它做软件元数据时，L0 的
  `desc & (DBM | S2AP_W)` 联合判断会把 L1 的只读页读成可写 → **L2 可写穿 L1 设定的只读页**
  （L1→L2 安全边界击穿），且 L2 写不再 fault，L1 自己的脏跟踪失效。
- **Leo 回应**："Yeah, for this to work on NV we need Oliver's patch series enabling HAFDBS
  emulation."（要跑在嵌套上需要 Oliver 的 HAFDBS 模拟系列。）——承认依赖但**代码没动**。
- **我们的立场**：这个洞是**当下的**（不需要等 Oliver），短期应 revert 成只读 S2AP_W——
  代价只是"L1 用新编码时 WC 被误判只读"的性能回退（写 fault 多注回一层，安全无损）。
  正确修复是 gate 在"L1 的虚拟 VTCR_EL2.HD==1"上，那才是 bit51 身份的权威来源。
- **拟问 Leo**："Oliver 系列落地前，这行能不能先退回只看 S2AP_W？或者至少 cover letter
  显式声明这个前置依赖，避免有人只拿 patch 1 用在开嵌套的 host 上。"

### N6. v2 边界：我们的 fixup 他收不收

**与 sashiko 的关系**：自查（协作问题）。

- **背景**：我们在 code_v5_3_leo 带了六个修复（F1 HA 成对 / F2 拆账 / F3 TLBI /
  F4 动态判断 / R1 三态状态机 / harvest 收割），全部独立成 commit、commit message 里
  标了 "This is a fixup of Leonardo Bras' ..."。
- **先例**：patch 4 线程里他说过 "The main reason for this patch series (at least up to
  patch #3) was to give you a base for HDBSS, so please rebase as much as you want on
  top of it."（这个系列至少到 patch 3 就是给你做 HDBSS 地基的，随便 rebase。）
- **拟问 Leo**："F1-F4 这几个 fixup 你 v2 想直接收编吗？收编的话我们就不在自己的系列里
  重复携带；R1 三态状态机（含 HDBSS 腿）体量较大，也可以留在我们 HDBSS 系列里，
  你只收 HAFDBS 腿。边界你怎么划？"

### N7. RELOAD-before-wp 顺序依赖文档化

**与 sashiko 的关系**：自查，但**直接支撑 sashiko TLBI 条（#3）里 Leo 的开向辩护**——
他说的"后续 wp+flush 兜底"能成立，靠的正是这个顺序。

- **问题**：整个 enable-logging 方向的正确性建立在"模式翻转的 RELOAD（KVM_REQUEST_WAIT）
  返回后无 vCPU 在 guest 里 → wp 的 WRITE_ONCE 不与硬件升级并发"之上。这是我们从
  KVM_REQUEST_WAIT 语义推导的，**代码里没有任何注释**，将来重构 commit_memory_region
  的人不知道这个顺序不能动。
- **证据**：`hafbs_only_path_verification.md` 不变式 I2；wp 裸写（N1）不炸也靠它。
- **拟问 Leo**："RELOAD 先于 wp 这个顺序是 intentional 的吧？能不能在
  kvm_arch_commit_memory_region 里注释说明'必须先静默 vCPU 再 wp'，防止重排？"

### N8. 非迁移 HAFDBS 的性能数据

**与 sashiko 的关系**：**sashiko patch 5 性能条（#4）的后续**。

- **背景**：Leo cover letter 原话 "On (2), I really just want feedback to understand if
  it's worth pursuing."（第二个目标我就是要反馈，看值不值得做。）
- **我们的输入**：受益画像是 server/headless VM（无 VGA logging，HD 常开）；desktop VM 被
  VGA 悬崖抵消（F4 修复后悬崖消失但 HAFDBS 收益也只剩"迁移开始 wp 更快"）。
- **拟问 Leo**："你手上有没有 benchmark（wp 加速、fault 率对比）？我们可以在 headless
  server 形态上帮忙跑数据——不过需要先知道你预期的受益工作负载是什么。"

### N9. SMMU 共享 S2 前瞻：WC 页对无 HTTU SMMU 是 RO

**与 sashiko 的关系**：自查，前瞻讨论。

- **问题**：S2 共享（SMMU 直挂 KVM stage-2）落地后，WC 页 (S2AP=01, DBM=1) 对不支持
  HTTU-dirty 的 SMMU（IDR0.HTTU < 2，现存硬件大量）就是 RO——设备 DMA 写直接失败，且
  设备 fault 无 CPU 那种 relax 兜底。SVA 先例：SMMU 共享进程 stage-1 表时驱动必须开
  CD.TCR.HA|HD 才能正确理解 CPU 的 PTE（"PTE_WRITE and PTE_DBM share the same bit"）。
- **拟问 Leo**："系列对 SMMU S2 sharing 的方向怎么看？如果那是可见未来，kvm_supports_hafdbs
  是不是该预留'无直通设备或 SMMU dbm_capable'的 gate？（详细分析见
  dbm_blindspots_and_risks.md §5）"

### N10. 三态编码的 selftests 计划

**与 sashiko 的关系**：自查。

- **问题**：系列目前零测试。三态编码 + 状态机翻转 + CLEAR 竞态都是可测的：
  ptdump D/C 列断言（debugfs）、wrprotect round-trip（WD→WC→写 fault→WD）、
  迁移开始/结束的 HD 翻转行为、folio 账（`/proc/vmstat` nr_dirty 观察）。
- **拟问 Leo**："v2 有没有 selftests 计划？我们可以贡献三态相关的用例。"

---

## 附录 A：英文邮件原稿（供翻译参考）

> 以下是此前拟好的英文邮件体（回复 lkml 线程 `[RFC PATCH 2/5]`，覆盖第一部分 #1-#5 的
> 表述）。翻译新问题时可复用其中的技术措辞。原有的中文对照块已删除——第一部分即权威
> 中文分析。

**To:** Leonardo Bras \<leo.bras@arm.com\>
**Cc:** linux-arm-kernel@lists.infradead.org, kvmarm@lists.linux.dev, Oliver Upton, Marc Zyngier
**Subject:** Re: [RFC PATCH 2/5] KVM: arm64: Add KVM_PGTABLE_PROT_DIRTY

Hi Leo,

Thanks for the series, and for walking through the sashiko findings. A few
comments, mostly cross-checking against how stage-1 handles the same
problems — it turns out the core kernel already has precedents for each
of the gaps below.

## 1. Releasing the folio as dirty: agree, but the two "dirty" accounts must be split

I agree with your conclusion that kvm_release_faultin_page() should use
writable rather than clean. One refinement: the series currently derives
both consumers from the same expression:

```c
	bool dirty = prot & KVM_PGTABLE_PROT_DIRTY;          /* kvm_s2_fault_map() */

	kvm_release_faultin_page(kvm, s2vi->page, !!ret, dirty);   /* host folio account */
	...
	if (dirty && !ret)
		mark_page_dirty_in_slot(...);                    /* KVM dirty bitmap account */
```

These are two different ledgers with different precision requirements:

- **host folio dirty** (SetPageDirty) — for reclaim/writeback
  correctness. Must be *speculative*: any mapping that *could* be made
  writable locklessly has to mark the folio dirty at fault time. The
  existing comment in kvm_release_faultin_page() says exactly this
  ("KVM must (somewhat) speculatively mark the folio dirty if KVM could
  locklessly make the SPTE writable"), and x86 relies on it for the same
  reason (hardware dirty updates need no VM exit).
- **KVM dirty bitmap** (mark_page_dirty_in_slot) — for migration. Must
  be *exact*: a read-faulted WC page must not enter the bitmap, or
  pre-copy will ship clean pages.

So I'd suggest:

```c
	kvm_release_faultin_page(kvm, s2vi->page, !!ret,
				 prot & KVM_PGTABLE_PROT_W);       /* speculative */
	...
	if ((prot & KVM_PGTABLE_PROT_DIRTY) && !ret)             /* exact */
		mark_page_dirty_in_slot(...);
```

and the same split in gmem_abort().

For the long term, stage-1 closes this hole at unmap time: on zap, the
generic mm does

```c
	/* mm/memory.c, zap_present_folio_ptes() */
		if (pte_dirty(ptent))
			folio_mark_dirty(folio);
```

i.e. the dirty state harvested from the PTE is pushed back into the folio
when the mapping is torn down, no matter who set it (software pte_mkdirty
or a hardware DBM update). The arm64 KVM unmap walker currently only puts
the page-table page; harvesting S2AP_W there (and before the write-protect
clear) would make the folio account exact at the mapping lifecycle ends.
We have that working on top of the HDBSS tree, along with the speculative
marking above.

## 2. VTCR_EL2.HD without HA

Patch 5 enables HD alone:

```c
	kvm->arch.mmu.vtcr |= VTCR_EL2_HD;
```

Three reference points suggest HA must come along:

- The SMMUv3 driver, in the equivalent situation (walking descriptors
  whose writable bit *is* the DBM bit), always sets both:
  "To enable dirty flag update, set both Access flag and dirty state
  update" (arm-smmu-v3.c, arm_smmu_make_s1_cd()), and the SVA CD enables
  CD.TCR.HA|HD together ("PTE_WRITE and PTE_DBM share the same bit",
  arm-smmu-v3-sva.c).
- The kernel's own stage-1 enablement path sets HA first (proc.S,
  __cpu_setup) and HD later via the ARM64_HW_DBM capability.
- The spec requirement for FEAT_HDBSS is that HDBSS is only enabled
  when VTCR_EL2.{HDBSS,HA,HD} are all 1 (D8.5.2.3).

Unless the ARM ARM says VTCR_EL2.HD has no such dependency, I'd suggest
`VTCR_EL2_HD | VTCR_EL2_HA`. Side benefit: hardware-managed AF kills the
access-flag exits on mmu-notifier aged pages.

## 3. No TLB invalidation on the HD flip

cpu_enable_hw_dbm() pairs the TCR_EL1.HD flip with isb() +
local_flush_tlb_all(). For the VTCR flip, kvm_set_hafdbs() only requests
KVM_REQ_RELOAD_STAGE2. For the enable-logging direction the subsequent
kvm_mmu_wp_memory_region() + kvm_flush_remote_tlbs_memslot() happens to
cover us, but that ordering dependency is implicit, and for the
disable-logging direction (HD off→on) stale read-only cached translations
keep faulting until each page takes its next fault. Either a
kvm_flush_remote_tlbs(kvm) in kvm_set_hafdbs() or at least a comment
documenting the caller-side TLBI responsibility would make this robust.

## 4. Static vs dynamic HAFDBS check in compute_prot

kvm_s2_fault_compute_prot() decides WC based on the static
kvm_supports_hafdbs(kvm), but HD is flipped off globally as soon as any
single memslot starts logging. Note this is not just migration: QEMU's
VGA keeps KVM_MEM_LOG_DIRTY_PAGES on the VRAM slot for the whole runtime
of a desktop VM. With HD off but the static check still true, every read
fault on the non-logged RAM slots installs WC, which is RO under HD=0 —
one extra fault per page, for the most common "not migrating" workload.

Reading the actual state (`kvm->arch.mmu.vtcr & VTCR_EL2_HD`) instead of
the capability would keep the optimization honest; alternatively
kvm_set_hafdbs(0) could bulk-promote existing WC pages to WD so only the
pages mapped before the flip pay the one-time cost.

## 5. Minor: vtcr race, and nested bit 51

On the setup_vcpu vs kvm_set_hafdbs race sashiko flagged: rather than
adding slots_lock to kvm_setup_vcpu(), making the HD bit a pure derived
value (capability && nr_memslots_dirty_logging == 0, recomputed on each
event) would remove the lost-update window entirely.

And just to make sure it's on the radar: the walk_nested_s2_pgd()
`desc & (DBM | S2AP_W)` union reading depends on Oliver's nested HAFDBS
emulation to be safe — until L1's view of HAFDBS.DBM exists, bit 51 is
RES0 from L1's perspective and an honest L1 could use it as software
metadata. Maybe worth an explicit note in the cover letter that the
nested change rides on that series, or a temporary revert to S2AP_W-only
until it lands.

Happy to test any of the above on top of our HDBSS tree — we're rebasing
v5 onto this series as discussed on patch 4.

Thanks,
Tian
