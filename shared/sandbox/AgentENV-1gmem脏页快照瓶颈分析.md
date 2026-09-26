# `snapshot_creation_1gmem` 脏页快照瓶颈分析报告

**交付类型:纯分析,无代码改动**(用户已确认只要分析结论)。

## Context

用户询问 `snapshot_creation_1gmem`(crates/benchmarks/benches/snapshot_benchmark.rs)压测中带脏页快照的瓶颈在哪。该 benchmark 计时窗口只包住 `FirecrackerSandbox::pause()`;被测 VM 为 1536MiB / 1 vCPU,prepare 阶段在 guest 内执行 `dd if=/dev/zero of=/dev/shm/bench_1g bs=1M count=1024`(约 1GiB 全零脏页)。本报告基于对 AgentENV 与 FireCracker 两侧源码的逐行追踪,给出窗口内各步骤成本分解与瓶颈定位。

## 结论(TL;DR)

**窗口内 ~90%+ 时间花在 `convert_dirty_memory_to_overlaybd` 的数据拷贝循环**,且它慢是三个结构性问题的叠加:

1. **`concurrency=32` 结构性无效,整条拷贝严格单线程**;
2. **32 KiB 硬编码 chunk 粒度**,每 GiB ≈ 65k 次系统调用 + 32k 次堆分配 + ~3× 内存带宽;
3. **零页检测是死代码**,benchmark 的 1GiB 全零脏页被逐字节照抄进层文件。

## 1. 计时窗口步骤分解(按执行顺序)

| # | 步骤 | 内容 | 成本模型 | 占比 |
| --- | --- | --- | --- | --- |
| 1 | managed root 准备 | `live_snapshot_root()` + mkdir(sandbox.rs:928-931) | 几个 syscall | 忽略 |
| 2 | VM 暂停 | PATCH /vm → vCPU Pause 事件握手(instance.rs:447-453) | ~0.1-2ms | 忽略 |
| 3 | state-only 快照 | PUT /snapshot/create(Diff,无 mem_file)→ `save_state` 只序列化设备/vCPU/KVM 状态,**不碰 guest 内存**;~100KB `vm_state.bin` + 窗口内**唯一 fsync**(persist.rs:174-219) | ~1-20ms | 小 |
| 4 | 脏页区间 | GET /vm/dirty-memory-ranges:1536MiB = 1 个 slot,1 次 `KVM_GET_DIRTY_LOG`(48KB bitmap)+ 两次 393,216 位遍历(`store_dirty_bitmap` 保留 + `append_dirty_ranges` 合并);响应 KB 级 JSON | ~几 ms | 小 |
| 5 | **内存层转换** | `convert_dirty_memory_to_overlaybd`(overlaybd_snapshot.rs:773)→ `compact_to` | **见 §2** | **~90%+** |
| 6 | mem_image.json | Fresh 启动无继承层,不触发第二次 compaction,只写小 JSON | 忽略 | 忽略 |
| 7 | rootfs 封口 | restack 封开机以来的 upper(仅几十 MiB):close_seal 追加索引/trailer + rename + 新空 upper | ~几十 ms | 小 |
| 8 | manifest | 内存内构建 | 忽略 | 忽略 |

窗口内**无内存层 fsync**(只有 rename,overlaybd_snapshot.rs:670)——刷盘成本被推迟到窗口外的内核 writeback。

## 2. 瓶颈详解:`compact_to` 拷贝循环

数据通路:脏区间 → ~129 个 SegmentMapping(≤16,383 扇段 ≈ 8MiB,`Segment::MAX_LENGTH`,index.rs:18)→ Phase 1 切成 **32 KiB CompactChunk**(每 GiB ~32,768 个)→ Phase 2 逐个执行 [分配 32KiB Vec + memset → `process_vm_readv` 读 FC 进程 guest 内存 → `pwrite` 写层文件]。

### 2.1 单线程执行(concurrency=32 完全无效)

- Phase 2 用 `stream::iter(chunks).map(...).buffer_unordered(32)`(helper.rs:1544-1563),看似 32 路并发;
- 但读侧 `ProcessVmReader::read_at_into` 是 **inline 同步 `process_vm_readv`**(process_vm_reader.rs:24-99,代码自带 TODO 承认阻塞 tokio worker),写侧 `LocalFile::write_at` 是 **inline 同步 `pwrite`**(local.rs:606-608,同样有 TODO);
- 每个 chunk future 在第一次 `poll` 内同步完成、永不返回 `Pending` → `FuturesUnordered` 严格串行,**1 GiB 读+写全部跑在 `block_on` 的单个调用线程上**;
- `ProcessVmReader` 本身**没有锁**——串行是执行模型造成的,不是锁;多线程 runtime 的 worker 数也帮不上忙;
- `DIRECT_MEMORY_SNAPSHOT_COMPACTION_CONCURRENCY = 32`(overlaybd_snapshot.rs:46)在这条 writer/source 组合上买不到任何并行。

### 2.2 32 KiB chunk 粒度

- `VirtualFileWriter::new` 硬编码 `buf_size = 32 KiB`(virtual_file.rs:206-220);`with_buffer_size` 存在但无人调用;`MAX_IO_SIZE = 4 MiB`(types.rs:14)不在这条路径上生效;
- 每 GiB 脏页:~32,768 次 `vec![0u8; 32768]` 分配+memset(**随后被 read 完全覆盖,memset 纯浪费**)+ 32,768 次 readv + 32,768 次 pwrite;
- 合计 ≈ **65,536 次系统调用、32,768 次堆分配/释放、~3× 内存带宽**(memset + 跨进程拷贝 + page cache 写),全部单核。

### 2.3 零页检测是死代码

- `COMPACT_ZERO_DETECTION_ENABLED = false`(编译期常量,types.rs:17);
- `compact_is_zero_block` 忽略 buffer 内容返回常量(helper.rs:1118-1122)——**即使打开,现状实现也会把所有块判为零,扫描本身未实现**;
- 内存快照路径的 mapping 恒为 `zeroed=false`(overlaybd_snapshot.rs:736-742,第 4 参硬编码);
- 后果:benchmark 的 1GiB 全零脏页(`dd if=/dev/zero`)被逐字节照抄;
- **格式层其实完整支持零页**:写入侧 `zeroed` mapping 跳过目标空间(helper.rs:1470-1477),读取侧直接填零、不读数据(readonly.rs:272-276)——是一项"可用而未启用"的能力,对零页占比高的负载(本 benchmark 是极端 case,真实负载的匿名零页也常见)可让层大小骤降。

### 2.4 放大因素

- **脏集不是恰好 1 GiB**:脏追踪从开机累积且 API 非清除(swagger "logically non-clearing"),实际 ~1.1-1.4 GiB;
- 无 fsync 意味着 1 GiB+ 脏 page cache 可能在拷贝循环中途触发内核 writeback 限流(取决于 benchmark tmpdir 位于 tmpfs 还是真实磁盘)。

## 3. 每 GiB 脏页的量化成本模型

| 项 | 量级 |
| --- | --- |
| 系统调用 | ~65,536(readv + pwrite 各 32,768,均 32 KiB) |
| 堆分配 | 32,768 次 32 KiB alloc + free |
| 内存带宽 | ~3 GiB(memset 1 + readv 拷贝 1 + pwrite 1) |
| CPU 并行度 | 1(单核打满) |
| 层文件大小 | ≈ 脏字节数(无零页消减) |

单核有效吞吐按 ~0.5-2 GB/s 估算 → **~0.5-2 s/GiB**,与 benchmark 观察量级一致;窗口内其余步骤合计仅几十毫秒,相差 1-2 个数量级。

## 4. 次要因素

- `vm_state.bin` 的 fsync(窗口内唯一 fsync,~100KB 文件):~1-20ms;
- rootfs restack:开机 upper 几十 MiB,~几十 ms;
- dirty-ranges 位图两遍遍历:~几 ms。

## 5. 附录:优化杠杆(按影响排序,仅供参考,不在本次交付内)

1. **真并行化**:让 chunk future 真正挂起(owned buffer + `spawn_blocking`),`buffer_unordered(32)` 才会真正重叠;`ProcessVmReader` 无锁,天然可并行;
2. **chunk 提到 1-4 MiB**(`VirtualFileWriter::with_buffer_size`):16-64× 削减系统调用与分配;
3. **实现真正的零页扫描**(需先修复 stub):对零页多的负载层大小骤降,写侧成本同步消失(读侧仍需读以检测);
4. buffer 池化 / 去掉无意义 memset;
5. mem_convert 与 rootfs restack 并行(窗口内两个独立 await)。

## 6. 附录:实测验证方法(如需确认)

- `strace -c -f` 跟踪 bench 进程:期望 ~65k 次 readv/pwrite per GiB,单次 32,768 字节;
- `perf stat`:单核饱和;
- 层文件大小 ≈ 脏字节数(证明零页未被消减);
- `snapshot_creation` 与 `snapshot_creation_1gmem` 的差值 ≈ mem_convert 净耗时。

## 7. 内存层转换内部机制(流程图)

**一句话:问 FC"哪些页脏了",拿到清单,把清单上的页一块块从 FC 进程拷进一个新文件,最后在文件里写一张"目录"(index)记下每块数据属于内存的哪个位置。**

### 图 7-1:总览——内存层转换就是"按清单搬运"

```
 AgentENV(执行 pause)         FireCracker 进程(已暂停)              磁盘
 ───┬────────────────────────────┬────────────────────────────────────┬─────────────
    │                            │                                    │
    │ ① 创建 state 快照 ────────→ │ 写 vm_state.bin                    │
    │                            │ (设备+CPU状态,~百KB,不含内存)       │
    │                            │                                    │
    │ ② 要"脏页清单" ───────────→ │ 扫 KVM 脏位图(S2标脏)               │
    │ ←────── 脏页清单(图7-2) ────│                                    │
    │                            │                                    │
    │ ③ 按清单逐块搬运(图7-3):      │                                    │
    │    process_vm_readv ──────→ │ 把脏页从 FC 进程内存拷出来            │
    │    pwrite ──────────────────────────────────────────────────────→│ 写入层文件
    │    (循环 ~32768 次/GiB)     │                                    │
    │                            │                                    │
    │ ④ 写"目录"(index) + 封口 ──────────────────────────────────────→│ 完成
```

### 图 7-2:脏页清单——FC 给的每条都是一句"搬运指令"

```
    base_host_virt_addr: 0x7f200000    ← 源头:数据现在在 FC 进程的这个地址
    image_offset:        0x00100000    ← 目的地:属于"内存镜像"的这个位置
    length:              0x40000000    ← 搬 1 GiB

 读法:"恢复用的内存镜像,从第 1MiB 开始的 1GiB,
       现在去 FC 进程的 0x7f200000 处拿。"

 注① image_offset 不是物理地址 GPA(物理地址有 MMIO 洞),
     是 FC 拍平后的"镜像偏移"。
 注② AgentENV 把清单转成 512B 扇区单位,并把 HVA 塞进 mapping 的
     moffset 字段传给拷贝引擎——"FC 进程内存"就这样被
     伪装成一个普通源文件(compact_to 只把它当源偏移用)。
```

### 图 7-3:搬运流水线(compact_to 三阶段)

```
 【Phase 1】切块(纯 CPU,只算不搬)

   清单区间(每个 ≤8MiB)                切成 32KiB 小块
   ┌───────────┬───────────┬───┐      ┌──┬──┬──┬──┬── … ──┬──┐
   │   8MiB    │   8MiB    │ … │  →   │  │  │  │  │        │  │
   └───────────┴───────────┴───┘      └──┴──┴──┴──┴──     └──┘
    (1GiB 连续 ≈ 129 个区间)            每 GiB ≈ 32768 块
                                       每块 = 一条指令:
                                       "从 HVA X 读 L 字节 → 写到文件偏移 D"

 【Phase 2】搬运(对每块执行 4 步 —— 实际严格串行!)

        FC 进程内存         ①分配 32KiB 缓冲            层文件 .tmp
       ┌───────────┐          ┌───────────┐             ┌───────────┐
       │  脏页      │ ─②readv→ │  32KiB    │ ─④pwrite──→ │   数据     │
       └───────────┘  内核跨   └───────────┘   写页缓存    └───────────┘
                       进程拷贝      ↑
                            ③记账一条:"镜像偏移 → 文件偏移"

 【Phase 3】封口
   32768 条记账 ──合并相邻──→ ~129 条 ──→ 写成 index 区(每条 16 字节)
   + 开头 4KB header + 结尾 4KB trailer(记录 index 在哪)→ 完成
```

### 图 7-4:产出的层文件——为什么叫"稀疏增量"

```
 逻辑视角:内存镜像(恢复时的完整地址空间,固定 1.5GiB)

   0        1MiB                        ~1.1GiB                     1.5GiB
   ├─────────┬──────────────────────────────┬───────────────────────────┤
   │ ░░░░░░  │ ████████████████████████     │  ░░░░░░░░░░░░░░░░░░░░░░  │
   └─────────┴──────────────────────────────┴───────────────────────────┘
                ██ = 这个位置的数据存在本层      ░ = 不存(读时落下层/补零)
                (示意:实际脏区是多条区间,简化画成一段)

 物理视角:层文件(实际占盘 ≈ 脏页总量 + ~12KB)

   ┌──────────┬───────────────────────────────────┬──────────┬────────┐
   │ 4KB hdr  │   脏页数据,紧密排列,没有空洞        │  index   │ 4KB trl│
   │ vsize=1.5G│   (脏页总量 + 开机以来的脏)         │~129×16B  │        │
   └──────────┴───────────────────────────────────┴──────────┴────────┘
                     ↑ "目录":镜像第 X 字节 → 文件第 Y 字节的对应关系
```

虚拟大小 = 整个 guest 内存,物理大小 ≈ 脏页量——**没脏的区域一个字节都不占,这就是"增量层"**。

### 图 7-5:闭环——resume 时这层文件怎么被用

```
 resume 快照时:
   mem_image.json ──→ ublk 块设备 ──→ FC 把它当"内存后端文件" mmap 成 guest 内存

 guest 访问内存镜像偏移 X 时,层栈从上往下找:

   ┌────────────────────────────────┐
   │ 新 delta 层(本次抓的脏页)       │ ← X 在它的 index 里?读它
   ├────────────────────────────────┤
   │ 上一代 delta 层(如有)           │ ← 在?读它
   ├────────────────────────────────┤
   │ 基础层(最初抓的内存)            │ ← 在?读它
   └────────────────────────────────┘
                  ↓ 都不在
              补零(恰好正确:guest 内存初始就是全零,
                    从没被写过的页读 0 是对的)
```

## 8. bpftrace 实测验证(2026-09 实测数据)

测试条件:`snapshot_creation_1gmem`,单个 sample 总耗时 ≈ **300ms**,bpftrace 抓内核 syscall。

### 8.1 实测 syscall 数据

| 系统调用/内核函数 | 次数 | 总耗时 | 单次均耗 | 备注 |
| --- | --- | --- | --- | --- |
| `pwrite64` | 26.5k | 180ms | ~6.8µs | 层文件数据写入(32KiB/次) |
| `process_vm_readv` | 26.6k | 89ms | ~3.35µs | 从 FC 进程读脏页(32KiB/次) |
| `write` | 17.3k | 17ms | ~1µs | vm_state 序列化等小块写,未细分 |
| `KVM_GET_DIRTY_LOG` | 1 | 8.73ms | — | 脏位图读取(1536MiB/1 slot) |
| `pread64` / `fsync` | — | ≈0ms | — | 确认窗口内无读盘、无刷盘 |
| `kvm_arch_mmu_enable_log_dirty_pt_masked` | 164,973 | 6.44ms | — | S2 写错误处理,**发生在 prepare/dd 阶段,窗口外** |

### 8.2 预测 vs 实测对照

| 预测(纯代码分析) | 实测 | 结论 |
| --- | --- | --- |
| 窗口 ~90%+ 耗在 convert(readv+pwrite) | (180+89)/300 = **89.7%** | ✅ 精确吻合 |
| 每 32KiB chunk 一对 readv+pwrite,严格 1:1 | 26.6k vs 26.5k | ✅ |
| 单线程串行,窗口被串行 syscall 时间填满 | 180+89+17+8.73 = 294.7ms ≈ 300ms,无并行空隙 | ✅ |
| 每 GiB 脏页 ≈ 32,768 对调用 | 26.6k 对 → 有效脏数据 ≈ **831MiB**(26.6k×32KiB) | ⚠️ 见 8.3 |
| vm_state 的 fsync 是窗口内唯一 fsync,~ms 级 | fsync ≈ 0ms(该存储无可刷脏页) | ✅ |
| GET_DIRTY_LOG 1 次,~ms 级 | 1 次 8.73ms | ✅ 同量级 |

单次成本核算:readv 3.35µs/32KiB ≈ **9.3GB/s** 跨进程拷贝;pwrite 6.8µs/32KiB ≈ **4.6GB/s** 页缓存写——两者都是 syscall+memcpy 主导的串行小 IO,与"结构性串行"的判断一致。写侧耗时是读侧的 2 倍(页缓存分配/拷贝开销 > 跨进程读)。

### 8.3 重要发现:"1gmem" 实际是 "~0.8gmem"

实测搬运量 831MiB < dd 名义写入的 1GiB。最可能的解释链:

1. guest `/dev/shm` 是 tmpfs,**默认上限 = 50% RAM = 768MiB**(VM 内存 1536MiB);
2. `dd bs=1M count=1024`(1GiB)写满 ~768MiB 后 **ENOSPC 失败退出**;
3. benchmark 的 `dirty_1g_mem`(snapshot_benchmark.rs:183-193)调 `run_command(...).await?` 但**不检查 `ProcessOutput::exit_code`**(process.rs:55-62)——失败被静默吞掉;
4. 实际脏集 = ~768MiB(dd)+ ~60MiB(开机脏页)≈ **831MiB**,与 26.6k×32KiB = 831MiB 吻合到 1% 以内;
5. 旁证:`kvm_arch_mmu_enable_log_dirty_pt_masked` 164,973 次 ≈ 写错误次数,× 4KiB ≈ 645MiB,同量级佐证实际写入 ~0.7-0.8GiB。

**结论:瓶颈归因、调用配对、串行模型全部实测确认;同时暴露一个 benchmark 缺陷——建议 `dirty_1g_mem`(及 `write_1g_disk`)检查 `exit_code`,或显式挂载 /dev/shm(`mount -o remount,size=100% /dev/shm`),否则 1gmem 变体实际测的是 ~0.8GiB。** §2.4 中"脏集 ~1.1-1.4GiB"的估计应据此修正为 ~0.83GiB(受 tmpfs 上限截断)。

## 涉及文件(只读分析,无改动)

- crates/benchmarks/benches/snapshot_benchmark.rs(计时窗口)
- src/sandbox/firecracker/sandbox.rs:928-1140(pause 流水线)
- src/sandbox/firecracker/process_vm_reader.rs(读侧)
- src/sandbox/firecracker/overlaybd_snapshot.rs:46,652-799(转换入口)
- storage/overlaybd/src/lsmt/file/helper.rs:1401-1614(compact_to)
- storage/overlaybd/src/io/virtual_file.rs:206-256(32KiB writer)
- storage/overlaybd/src/backend/local.rs:589-608(inline pwrite)
- storage/overlaybd/src/lsmt/file/types.rs:17(零检测开关)
- firecracker/src/vmm/src/{vstate/vm.rs,persist.rs,rpc_interface.rs}(FC 侧步骤)
