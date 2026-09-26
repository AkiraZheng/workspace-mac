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
