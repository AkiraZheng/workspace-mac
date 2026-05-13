# QEMU NUMA 命令行参数解析实现分析

## 一、整体架构

QEMU 的 NUMA 参数解析分为三个层次：

```
命令行字符串 → QemuOpts (裸字符串键值对) → QAPI 类型化对象 (OptsVisitor) → NUMA 状态 (NumaState)
```

### 涉及的关键文件

| 文件 | 角色 |
|------|------|
| `system/vl.c` | 命令行入口，匹配 `-numa` 选项，调用 `qemu_opts_parse_noisily` |
| `qapi/opts-visitor.c` | OptsVisitor 实现：将 flat key=value 转换为强类型 QAPI 对象 |
| `qapi/machine.json` | QAPI Schema 定义：NumaOptions/NumaNodeOptions/NumaDistOptions 等 |
| `qapi/qapi-visit-machine.c` | QAPI 自动生成的 visit 函数 |
| `hw/core/numa.c` | 核心解析逻辑：各类型的具体校验和 NumaState 填充 |
| `hw/core/machine.c` | `machine_set_cpu_numa_node`：CPU 到 NUMA 节点的拓扑映射 |
| `include/system/numa.h` | 数据结构定义：NodeInfo, NumaState, 常量 |
| `qemu-options.hx` | 帮助文本（用户文档） |

---

## 二、支持的五种 -numa 子类型

`-numa` 是一个 discriminated union，通过第一个参数 (type) 区分：

```
-numa node[,mem=size][,cpus=firstcpu[-lastcpu]][,nodeid=node][,initiator=node]
-numa node[,memdev=id][,cpus=firstcpu[-lastcpu]][,nodeid=node][,initiator=node]
-numa dist,src=source,dst=destination,val=distance
-numa cpu,node-id=node[,socket-id=x][,core-id=y][,thread-id=z]
-numa hmat-lb,initiator=node,target=node,hierarchy=...,data-type=...[,latency=lat][,bandwidth=bw]
-numa hmat-cache,node-id=node,size=size,level=level[,associativity=...][,policy=...][,line=size]
```

---

## 三、第一层：命令行字符串 → QemuOpts

### system/vl.c:2986-2996 — 匹配 -numa 选项

```c
case QEMU_OPTION_numa:
    opts = qemu_opts_parse_noisily(qemu_find_opts("numa"),
                                   optarg, true);
    if (!opts) {
        exit(1);
    }
    break;
```

### qemu_opts_parse_noisily 内部做了什么

对于输入 `-numa node,cpus=0-2,cpus=5,nodeid=0`：

1. 在字符串中找第一个逗号，前面部分为第一个 token：`"node"`
2. 第一个 token 没有 `=` → 因为 `qemu_numa_opts.implied_opt_name = "type"` → 自动变成 `type=node`
3. 后续逗号切割：
   - `cpus=0-2`
   - `cpus=5`
   - `nodeid=0`
4. 每个 `key=value` 创建一个 QemuOpt 节点，挂在 QemuOpts 链表上
5. 同名 key 多次出现全部保留

结果链表：

```
QemuOpts (name="numa"):
  {name="type",   str="node"}
  {name="cpus",   str="0-2"}
  {name="cpus",   str="5"}
  {name="nodeid", str="0"}
```

### 关键限制：逗号是 QemuOpts 的参数分隔符

这意味着不能在单个 cpus= 值内用逗号分隔多个范围。`cpus=0-2,3` 是不合法的，因为 `,3` 会被当作一个裸的无键 token。正确写法是 `cpus=0-2,cpus=3`（多次指定同名 key）。

---

## 四、第二层：QemuOpts → QAPI 强类型对象 (OptsVisitor)

### hw/core/numa.c:737-740 — 延迟解析入口

```c
void parse_numa_opts(MachineState *ms)
{
    qemu_opts_foreach(qemu_find_opts("numa"), parse_numa, ms, &error_fatal);
}
```

在 `qemu_init()` 中，machine 对象创建完毕后统一调用。遍历所有收集的 `-numa` QemuOpts，对每个调用 `parse_numa`。

### hw/core/numa.c:518-553 — parse_numa 回调

```c
static int parse_numa(void *opaque, QemuOpts *opts, Error **errp)
{
    NumaOptions *object = NULL;
    MachineState *ms = MACHINE(opaque);
    Error *err = NULL;
    Visitor *v = opts_visitor_new(opts);         // 创建 OptsVisitor

    visit_type_NumaOptions(v, NULL, &object, errp);  // 核心：QAPI 类型化访问
    visit_free(v);
    if (!object) {
        return -1;
    }

    // === 兼容旧格式 mem=1024 (无单位，默认 MiB) ===
    if ((object->type == NUMA_OPTIONS_TYPE_NODE) && object->u.node.has_mem) {
        const char *mem_str = qemu_opt_get(opts, "mem");
        int ret = qemu_strtosz_MiB(mem_str, NULL, &object->u.node.mem);
        if (ret < 0) {
            error_setg_errno(&err, -ret, "could not parse memory size '%s'",
                             mem_str);
        }
    }

    if (!err) {
        set_numa_options(ms, object, &err);      // 分发到具体类型
    }

    qapi_free_NumaOptions(object);
    if (err) {
        error_propagate(errp, err);
        return -1;
    }
    return 0;
}
```

### OptsVisitor 状态机

OptsVisitor 是整个解析的核心。它实现了一个有限状态机：

```
                    opts_start_struct()
  ┌──────┐             构建哈希表          ┌─────────────┐
  │LM_NONE│ ─────────────────────────────→ │LM_IN_PROGRESS│
  └──────┘                                └──────┬──────┘
                                                  │
                  ┌───────────────────────────────┤
                  │                               │
                  │ opts_start_list()             │ opts_type_str/bool/size
                  │ 查找同名 key 的 GQueue         │ 在 LM_NONE 下直接消费
                  ↓                               ↓
        ┌─────────────┐              ┌──────────────────┐
        │LM_IN_PROGRESS│              │ 回到 LM_NONE      │
        │ (列表模式)    │              │ (标量消费完毕)     │
        └──────┬──────┘              └──────────────────┘
               │
               │ opts_type_uint64 遇到 "a-b" 格式
               ↓
    ┌──────────────────┐
    │LM_UNSIGNED_INTERVAL│
    │ range_next=val     │
    │ range_limit=val2   │
    └──────┬───────────┘
           │
           │ opts_next_list 每次 +1
           │ 直到 range_next == range_limit
           ↓
    ┌─────────────┐
    │LM_IN_PROGRESS│ ← 回到列表模式，取下一个 QemuOpt
    └──────┬──────┘
           │
           │ 所有 QemuOpt 消费完毕
           ↓
    ┌────────────┐
    │LM_TRAVERSED│ ← 列表结束
    └────────────┘
```

### opts_start_struct — 构建哈希表 (opts-visitor.c:137-167)

```c
static bool opts_start_struct(Visitor *v, const char *name,
                              void **obj, size_t size, Error **errp)
{
    OptsVisitor *ov = to_ov(v);

    if (obj) {
        *obj = g_malloc0(size);                  // 分配 NumaOptions 内存
    }
    if (ov->depth++ > 0) {                       // 嵌套结构体跳过
        return true;
    }

    // depth == 0：构建 unprocessed_opts 哈希表
    ov->unprocessed_opts = g_hash_table_new_full(
        &g_str_hash, &g_str_equal, NULL, &destroy_list);

    QTAILQ_FOREACH(opt, &ov->opts_root->head, next) {
        assert(strcmp(opt->name, "id") != 0);
        opts_visitor_insert(ov->unprocessed_opts, opt);
    }
    // ... 处理 fake_id_opt ...
}
```

### opts_visitor_insert — 按 name 分组 (opts-visitor.c:116-133)

```c
static void opts_visitor_insert(GHashTable *unprocessed_opts,
                                const QemuOpt *opt)
{
    GQueue *list;

    list = g_hash_table_lookup(unprocessed_opts, opt->name);
    if (list == NULL) {
        list = g_queue_new();
        g_hash_table_insert(unprocessed_opts,
                           (gpointer)opt->name, list);
    }
    g_queue_push_tail(list, (gpointer)opt);
}
```

对于 `type=node, cpus=0-2, cpus=5, nodeid=0`，构建的哈希表：

```
unprocessed_opts:
  "type"   → GQueue[ {type, "node"} ]
  "cpus"   → GQueue[ {cpus, "0-2"}, {cpus, "5"} ]
  "nodeid" → GQueue[ {nodeid, "0"} ]
```

**关键设计**：同名 key 的多个 QemuOpt 按在原字符串中的顺序存入同一队列。
key 是字符串指针（不复制），和 QemuOpt::name 指向同一地址。

### opts_start_list — 开始列表遍历 (opts-visitor.c:227-245)

```c
static bool opts_start_list(Visitor *v, const char *name,
                            GenericList **list, size_t size, Error **errp)
{
    OptsVisitor *ov = to_ov(v);

    assert(ov->list_mode == LM_NONE);
    assert(list);
    ov->repeated_opts = lookup_distinct(ov, name, errp);  // 查找 "cpus" 的 GQueue
    if (!ov->repeated_opts) {          // 可选字段不存在
        *list = NULL;
        return false;
    }
    ov->list_mode = LM_IN_PROGRESS;
    *list = g_malloc0(size);           // 分配 uint16List 头节点
    return true;
}
```

执行后：`ov->repeated_opts` 指向 `[{cpus,"0-2"}, {cpus,"5"}]`，`peek_head = "0-2"`。

### opts_type_uint64 — 整数解析与范围展开 (opts-visitor.c:451-501)

```c
static bool opts_type_uint64(Visitor *v, const char *name,
                             uint64_t *obj, Error **errp)
{
    OptsVisitor *ov = to_ov(v);
    const QemuOpt *opt;
    const char *str;
    uint64_t val;
    const char *endptr;

    if (ov->list_mode == LM_UNSIGNED_INTERVAL) {
        *obj = ov->range_next.u;          // 区间模式下直接返回计数器
        return true;
    }

    opt = lookup_scalar(ov, name, errp);
    if (!opt) { return false; }
    str = opt->str;                       // 取当前要解析的字符串

    if (parse_uint(str, &endptr, 0, &val) == 0) {
        if (*endptr == '\0') {            // 情况A：纯数字，如 "5"
            *obj = val;
            processed(ov, name);
            return true;
        }
        if (*endptr == '-' &&             // 情况B：范围语法，如 "0-2"
            ov->list_mode == LM_IN_PROGRESS) {
            uint64_t val2;

            str = endptr + 1;             // 跳到 '-' 后面
            if (parse_uint_full(str, 0, &val2) == 0 &&
                val <= val2 &&            // 起始值必须 <= 终止值
                val2 - val < OPTS_VISITOR_RANGE_MAX) {  // 范围跨度 < 65536

                ov->range_next.u = val;
                ov->range_limit.u = val2;
                ov->list_mode = LM_UNSIGNED_INTERVAL;  // 切换状态

                *obj = ov->range_next.u;  // 返回区间第一个值
                return true;
            }
        }
    }
    error_setg(errp, QERR_INVALID_PARAMETER_VALUE, opt->name,
               (ov->list_mode == LM_NONE)
                   ? "a uint64 value"
                   : "a uint64 value or range");
    return false;
}
```

**范围语法限制**：
- `val ≤ val2`：范围必须递增
- `val2 - val < 65536`：跨度不超过 65535
- 范围语法**仅在列表模式（LM_IN_PROGRESS）下生效**，标量模式下 `a-b` 不会被视为范围

### opts_next_list — 区间递增与 QemuOpt 消费 (opts-visitor.c:248-289)

```c
static GenericList *opts_next_list(Visitor *v, GenericList *tail, size_t size)
{
    OptsVisitor *ov = to_ov(v);

    switch (ov->list_mode) {
    case LM_TRAVERSED:
        return NULL;
    case LM_SIGNED_INTERVAL:
    case LM_UNSIGNED_INTERVAL:
        if (ov->list_mode == LM_SIGNED_INTERVAL) {
            if (ov->range_next.s < ov->range_limit.s) {
                ++ov->range_next.s;
                break;               // 仍在区间内
            }
        } else if (ov->range_next.u < ov->range_limit.u) {
            ++ov->range_next.u;
            break;                   // 仍在区间内
        }
        ov->list_mode = LM_IN_PROGRESS;  // 区间耗尽，回到列表模式
        /* fall through */

    case LM_IN_PROGRESS: {
        const QemuOpt *opt;
        opt = g_queue_pop_head(ov->repeated_opts);  // 弹出当前 QemuOpt
        if (g_queue_is_empty(ov->repeated_opts)) {
            g_hash_table_remove(ov->unprocessed_opts, opt->name);
            ov->repeated_opts = NULL;
            ov->list_mode = LM_TRAVERSED;  // 列表结束
            return NULL;
        }
        break;
    }
    }

    tail->next = g_malloc0(size);    // 分配下一个列表节点
    return tail->next;
}
```

### lookup_scalar — 获取当前应解析的 QemuOpt (opts-visitor.c:318-334)

```c
static const QemuOpt *
lookup_scalar(const OptsVisitor *ov, const char *name, Error **errp)
{
    if (ov->list_mode == LM_NONE) {
        // 标量模式：取同名的最后一个（覆盖语义）
        GQueue *list;
        list = lookup_distinct(ov, name, errp);
        return list ? g_queue_peek_tail(list) : NULL;
    }
    if (ov->list_mode == LM_TRAVERSED) {
        error_setg(errp, "Fewer list elements than expected");
        return NULL;
    }
    assert(ov->list_mode == LM_IN_PROGRESS);
    return g_queue_peek_head(ov->repeated_opts);  // 列表模式：取队头
}
```

### 范围展开完整时序 (输入 cpus=0-2,cpus=5)

```
步骤 1: start_list("cpus")
        repeated_opts = [{cpus,"0-2"}, {cpus,"5"}]
        peek_head = "0-2"
        list_mode = LM_IN_PROGRESS

步骤 2: type_uint64 (第1次)
        lookup_scalar → peek_head = "0-2"
        parse_uint("0-2") → val=0, endptr 指向 '-'
        检测到 '-' 且在 LM_IN_PROGRESS 模式
        val2=2, 0≤2 ✓, 2-0=2 < 65536 ✓
        → range_next=0, range_limit=2
        → list_mode = LM_UNSIGNED_INTERVAL
        → return 0  ←── uint16List[0]

步骤 3: next_list (第1次)
        range_next.u(0) < range_limit.u(2) → true
        ++range_next.u → range_next=1
        → return 新节点

步骤 4: type_uint64 (第2次)
        list_mode == LM_UNSIGNED_INTERVAL
        → return range_next.u = 1  ←── uint16List[1]

步骤 5: next_list (第2次)
        range_next.u(1) < range_limit.u(2) → true
        ++range_next.u → range_next=2
        → return 新节点

步骤 6: type_uint64 (第3次)
        list_mode == LM_UNSIGNED_INTERVAL
        → return range_next.u = 2  ←── uint16List[2]

步骤 7: next_list (第3次)
        range_next.u(2) < range_limit.u(2) → false
        区间耗尽 → list_mode = LM_IN_PROGRESS
        fall through →
        pop_head("0-2")  ← "0-2" 的这个 QemuOpt 被消费
        队列非空（还有 "5"）
        → return 新节点

步骤 8: type_uint64 (第4次)
        list_mode == LM_IN_PROGRESS
        lookup_scalar → peek_head = "5"
        parse_uint("5") → val=5, *endptr='\0'
        → *obj=5, processed()
        → return 5  ←── uint16List[3]

步骤 9: next_list (第4次)
        pop_head("5")  ← "5" 的 QemuOpt 被消费
        队列为空 → 删除 "cpus" 键
        list_mode = LM_TRAVERSED
        → return NULL  (列表结束)

步骤10: end_list
        list_mode = LM_NONE

最终 uint16List = [0, 1, 2, 5]
```

### opts_check_struct — 未知参数检测 (opts-visitor.c:170-191)

```c
static bool opts_check_struct(Visitor *v, Error **errp)
{
    OptsVisitor *ov = to_ov(v);
    GHashTableIter iter;
    GQueue *any;

    if (ov->depth > 1) {
        return true;
    }

    g_hash_table_iter_init(&iter, ov->unprocessed_opts);
    if (g_hash_table_iter_next(&iter, NULL, (void **)&any)) {
        const QemuOpt *first;
        first = g_queue_peek_head(any);
        error_setg(errp, "Invalid parameter '%s'", first->name);
        return false;
    }
    return true;
}
```

如果哈希表中还有未消费的 key（用户输入了不存在的参数名），报错 `"Invalid parameter 'xxx'"`。

---

## 五、第三层：强类型对象 → NumaState (类型分发与校验)

### set_numa_options — 分发器 (hw/core/numa.c:463-516)

```c
void set_numa_options(MachineState *ms, NumaOptions *object, Error **errp)
{
    if (!ms->numa_state) {
        error_setg(errp, "NUMA is not supported by this machine-type");
        return;
    }

    switch (object->type) {
    case NUMA_OPTIONS_TYPE_NODE:
        parse_numa_node(ms, &object->u.node, errp);
        break;
    case NUMA_OPTIONS_TYPE_DIST:
        if (!object->u.dist.has_val) { /* ... */ }
        parse_numa_distance(ms, &object->u.dist, errp);
        break;
    case NUMA_OPTIONS_TYPE_CPU:
        if (!object->u.cpu.has_node_id) {
            error_setg(errp, "Missing mandatory node-id property");
            return;
        }
        if (!ms->numa_state->nodes[object->u.cpu.node_id].present) {
            error_setg(errp, "Invalid node-id=%" PRId64
                       ", NUMA node must be defined with "
                       "-numa node,nodeid=ID before it's used with "
                       "-numa cpu,node-id=ID", object->u.cpu.node_id);
            return;
        }
        machine_set_cpu_numa_node(ms,
            qapi_NumaCpuOptions_base(&object->u.cpu), errp);
        break;
    case NUMA_OPTIONS_TYPE_HMAT_LB:
        if (!ms->numa_state->hmat_enabled) {
            error_setg(errp, "ACPI Heterogeneous Memory Attribute Table "
                       "(HMAT) is disabled, enable it with "
                       "-machine hmat=on");
            return;
        }
        parse_numa_hmat_lb(ms->numa_state, &object->u.hmat_lb, errp);
        break;
    case NUMA_OPTIONS_TYPE_HMAT_CACHE:
        if (!ms->numa_state->hmat_enabled) {
            error_setg(errp, "HMAT is disabled, enable it with "
                       "-machine hmat=on");
            return;
        }
        parse_numa_hmat_cache(ms, &object->u.hmat_cache, errp);
        break;
    default:
        abort();
    }
}
```

---

## 六、各子类型的边界校验完整列表

### 6.1 `-numa node,...` (parse_numa_node + numa_complete_configuration)

| 约束 | 限制值 | 错误信息 |
|------|--------|---------|
| nodeid < MAX_NODES | 128 | `"Max number of NUMA nodes reached: %u"` |
| nodeid 不重复 | — | `"Duplicate NUMA nodeid: %u"` |
| cpus 每个值 < max_cpus | smp 参数决定 | `"CPU index (%u) should be smaller than maxcpus (%d)"` |
| CPU 不重复分配到其他节点 | — | `"CPU is already assigned to node-id: %d"` |
| cpus 范围跨度 < OPTS_VISITOR_RANGE_MAX | 65536 | `"a uint64 value or range"` |
| mem 和 memdev 不能混用 | — | `"mixing both is not allowed"` |
| mem 需要机器类型支持 | — | `"Parameter -numa node,mem is not supported"` |
| memdev 必须解析到已存在的 memory-backend | — | `"memdev=%s is ambiguous"` |
| initiator < MAX_NODES | 128 | `"The initiator id %u expects an integer between 0 and %d"` |
| initiator 需要 -machine hmat=on | — | `"HMAT is disabled"` |
| node ID 必须连续（无空缺） | — | `"numa: Node ID missing: %d"` (exit) |
| 各节点内存之和 == -m 总 RAM | — | `"total memory for NUMA nodes (0x%lx) should equal RAM size"` (exit) |

### 6.2 `-numa dist,...` (parse_numa_distance + validate_numa_distance)

| 约束 | 限制值 | 错误信息 |
|------|--------|---------|
| src < MAX_NODES, dst < MAX_NODES | 128 | `"Parameter '%s' expects an integer between 0 and %d"` |
| src/dst 节点必须已声明 | — | `"Source/Destination NUMA node is missing"` |
| val >= NUMA_DISTANCE_MIN | 10 | `"NUMA distance (%u) is invalid, it shouldn't be less than %d"` |
| 本地距离 (src==dst) 必须为 10 | 10 | `"Local distance of node %d should be %d"` |
| 任意两个节点间至少有一个方向的距离 | — | `"The distance between node %d and %d is missing"` (exit) |
| 非对称时必须提供所有双向距离 | — | `"please provide distances for both directions of all node pairs"` (exit) |

常量定义 (`include/system/numa.h`)：
```c
#define MAX_NODES                 128
#define NUMA_DISTANCE_MIN          10
#define NUMA_DISTANCE_DEFAULT      20
#define NUMA_DISTANCE_MAX         254
#define NUMA_DISTANCE_UNREACHABLE 255
```

### 6.3 `-numa cpu,...` (machine_set_cpu_numa_node)

| 约束 | 错误信息 |
|------|---------|
| node-id 必填 | `"Missing mandatory node-id property"` |
| node-id 对应节点已声明 | `"NUMA node must be defined with -numa node,nodeid=ID before..."` |
| 机器不支持 thread-id | `"thread-id is not supported"` |
| 机器不支持 core-id | `"core-id is not supported"` |
| 机器不支持 socket-id | `"socket-id is not supported"` |
| 机器不支持 die-id | `"die-id is not supported"` |
| CPU 已分配到其他节点 | `"CPU is already assigned to node-id: %d"` |
| 必须至少匹配到一个 CPU | `"no match found"` |
| HMAT 下 CPU 节点的 initiator 必须为自身 | `"The initiator of CPU NUMA node %d should be itself"` |

### 6.4 `-numa hmat-lb,...` (parse_numa_hmat_lb)

| 约束 | 限制值 | 错误信息 |
|------|--------|---------|
| 需要 -machine hmat=on | — | `"HMAT is disabled"` |
| initiator ≤ num_nodes | 运行时 | `"Invalid initiator=%d, it should be less than %d"` |
| target ≤ num_nodes | 运行时 | `"Invalid target=%d, it should be less than %d"` |
| initiator 必须是 initiator 域 (有 CPU) | — | `"Invalid initiator=%d, it isn't an initiator proximity domain"` |
| target 节点必须存在 | — | `"The target=%d should point to an existing node"` |
| 延迟型必须有 latency | — | `"Missing 'latency' option"` |
| 延迟型不能有 bandwidth | — | `"Invalid option 'bandwidth' since the data type is latency"` |
| 带宽型必须有 bandwidth | — | `"Missing 'bandwidth' option"` |
| 带宽型不能有 latency | — | `"Invalid option 'latency' since the data type is bandwidth"` |
| 带宽值 Must 对齐 MiB | — | `"Bandwidth %lu...should be 1MB aligned"` |
| 不重复的 initiator-target 对 | — | `"Duplicate configuration of the latency/bandwidth"` |

### 6.5 `-numa hmat-cache,...` (parse_numa_hmat_cache)

| 约束 | 限制值 | 错误信息 |
|------|--------|---------|
| node-id 已存在 | — | `"Invalid node-id=%u, it should be less than %d"` |
| 该节点 hmat-lb 信息先提供 | — | `"The latency and bandwidth information of node-id=%u should be provided before"` |
| level ∈ [1, HMAT_LB_LEVELS) | [1,3] | `"Invalid level=%u, it should be larger than 0 and less than or equal to %d"` |
| 同 node-id+level 不重复 | — | `"Duplicate configuration of the side cache"` |
| 低级 cache 必须先定义 | — | `"Cache level=%u shall be defined first"` |
| size 逐级递增 | — | `"Invalid size=%lu, the size should be larger than the size of level=%u"` |

---

## 七、关键数据结构

```c
// include/system/numa.h
#define MAX_NODES 128

typedef struct NodeInfo {
    uint64_t node_mem;                     // 节点内存大小 (bytes)
    struct HostMemoryBackend *node_memdev; // 内存后端对象指针
    bool present;                          // 是否已声明
    bool has_cpu;                          // 是否有 CPU
    bool has_gi;                           // 是否有通用 initiator
    uint8_t lb_info_provided;              // hmat-lb 信息提供标记 (bit0=latency, bit1=bandwidth)
    uint16_t initiator;                    // 最近 initiator 节点
    uint8_t distance[MAX_NODES];           // 到各节点的距离
} NodeInfo;

struct NumaState {
    int num_nodes;                         // 实际节点数
    bool have_numa_distance;               // 是否设置了距离
    bool hmat_enabled;                     // HMAT 是否启用

    NodeInfo nodes[MAX_NODES];             // 所有节点信息

    HMAT_LB_Info *hmat_lb[HMAT_LB_LEVELS][HMAT_LB_TYPES];
    NumaHmatCacheOptions *hmat_cache[MAX_NODES][HMAT_LB_LEVELS];
};
```

```json
// qapi/machine.json - NumaNodeOptions
{ 'struct': 'NumaNodeOptions',
  'data': {
   '*nodeid': 'uint16',
   '*cpus':   ['uint16'],
   '*mem':    'size',
   '*memdev': 'str',
   '*initiator': 'uint16' }}

// qapi/machine.json - NumaDistOptions
{ 'struct': 'NumaDistOptions',
  'data': {
   'src': 'uint16',
   'dst': 'uint16',
   'val': 'uint8' }}
```

---

## 八、解析完整流程（以 -numa node,cpus=0-2,cpus=5,nodeid=0 为例）

```
输入: -numa node,cpus=0-2,cpus=5,nodeid=0
         │
         ▼   vl.c:2991
  qemu_opts_parse_noisily("numa", optarg)
    按逗号切割，implied_opt_name="type"
    QemuOpts 链表:
      {type, "node"}, {cpus, "0-2"}, {cpus, "5"}, {nodeid, "0"}
         │
         ▼   vl.c:3836 → numa.c:737
  parse_numa_opts(ms) → qemu_opts_foreach → parse_numa()
         │
         ▼   numa.c:523-525
  opts_visitor_new(opts) → opts_start_struct()
    构建 unprocessed_opts 哈希表:
      "type"   → [{type,"node"}]
      "cpus"   → [{cpus,"0-2"}, {cpus,"5"}]
      "nodeid" → [{nodeid,"0"}]
         │
         ▼   QAPI 自动生成代码
  visit_type_NumaOptions:
    ├─ visit_type_NumaOptionsType → "node" → NUMA_OPTIONS_TYPE_NODE
    └─ visit_type_NumaNodeOptions:
         ├─ opts_optional("nodeid") → found
         ├─ type_uint64("nodeid") → 0, processed
         ├─ start_list("cpus")
         │    ┌─────────────────────────────────────────┐
         │    │ for each: next_list + type_uint64       │
         │    │   "0-2" → LM_UNSIGNED_INTERVAL → 0,1,2 │
         │    │   "5"   → flat value → 5               │
         │    │ uint16List = [0, 1, 2, 5]              │
         │    └─────────────────────────────────────────┘
         ├─ end_list → LM_NONE
         ├─ opts_optional("mem") → not found
         ├─ opts_optional("memdev") → not found
         ├─ opts_optional("initiator") → not found
         └─ opts_check_struct → all consumed ✓
         │
         ▼   numa.c:543 → numa.c:472
  set_numa_options(ms, &{type=NODE, u.node={nodeid=0, cpus=[0,1,2,5]}})
    → parse_numa_node():
         ├─ nodenr = 0 (< 128 ✓, not duplicate ✓)
         ├─ initiator = MAX_NODES (default)
         ├─ for cpus in [0,1,2,5]:
         │    ├─ 0 < max_cpus ✓ → cpu_index_to_props → machine_set_cpu_numa_node ✓
         │    ├─ 1 < max_cpus ✓ → ... ✓
         │    ├─ 2 < max_cpus ✓ → ... ✓
         │    └─ 5 < max_cpus ✓ → ... ✓
         ├─ no mem/memdev → just declare the node
         ├─ present=true, max_numa_nodeid=1, num_nodes++
         └─ return
         │
         ▼   (所有 -numa 选项处理完毕) numa.c:644
  numa_complete_configuration(ms):
    ├─ 检查 node ID 不空缺 ✓
    ├─ 检查总内存 == RAM 大小 ✓
    └─ 校验距离表 ✓
```

---

## 九、典型不合法输入汇总

| 输入 | 原因 | 报错位置 |
|------|------|---------|
| `cpus=0-2,3` | 逗号被 QemuOpts 当分隔符，`3` 变裸 key | QemuOpts 解析层 |
| `cpus=0-100000` | 范围跨度 > OPTS_VISITOR_RANGE_MAX (65535) | opts-visitor.c:497 |
| `nodeid=128` | 达到 MAX_NODES 上限 | numa.c:79 |
| 重复 nodeid | `present==true` 的节点再次声明 | numa.c:85 |
| nodeid=0 和 nodeid=2 但没有 nodeid=1 | 稀疏 node ID | numa.c:681 (exit) |
| CPU 编号 >= max_cpus | 超出 smp 定义的总 CPU 数 | numa.c:115 |
| CPU 分配到两个不同节点 | slot 已有不同 node_id | machine.c:843 |
| `mem=` 和 `memdev=` 混用 | 互斥 | numa.c:134 |
| dist val=5 | < NUMA_DISTANCE_MIN(10) | numa.c:192 |
| src==dst 但 val!=10 | 本地距离必须为 10 | numa.c:199 |
| `-numa dist` 引用的节点不存在 | 未 declare | numa.c:186 |
| `-numa cpu` 缺少 node-id | 必填项 | numa.c:478 |
| `-numa cpu` 引用未声明的 node | `present==false` | numa.c:482 |
| `-numa cpu` 无任何 CPU 匹配 | `match==false` | machine.c:868 |
| `-numa hmat-lb` 未开 `-machine hmat=on` | 前置条件 | numa.c:494 |
| 总 NUMA 内存 ≠ RAM | 一致性 | numa.c:697 (exit) |
| `-numa cpu` 使用机器不支持的拓扑属性 | 如 RISC-V 用 socket-id | machine.c:783 |

---

## 十、关键设计要点

1. **逗号的两层语义**：逗号在 QemuOpts 层是参数分隔符，不能在值内部用作范围分隔符。范围用 `-`（如 `0-2`），不连续用多个 `cpus=`。

2. **OptsVisitor 的状态机**：LM_NONE → LM_IN_PROGRESS → LM_UNSIGNED_INTERVAL → LM_TRAVERSED。范围展开通过区间模式实现，一个 QemuOpt 字符串 `"0-2"` 可展开为多个列表元素。

3. **QAPI Schema 驱动**：`NumaOptions` 是 discriminated union，`NumaNodeOptions.cpus` 的类型 `['uint16']` 决定了它是一个 uint16 列表，OptsVisitor 据此处理重复 key 和范围展开。

4. **延迟校验**：部分校验（node ID 连续性、内存总量、距离对称性）推迟到 `numa_complete_configuration()` 中完成，因为此时所有 `-numa` 选项都已解析完毕，可以做全局一致性检查。

5. **兼容性处理**：legacy `mem=1024`（无单位默认 MiB）在 OptsVisitor 之后通过 `qemu_strtosz_MiB` 补救解析；warn_report 会警告用户使用 memdev。
