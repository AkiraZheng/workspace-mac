# 原理分析
Host 侧 mmap 路径
```c
// mlx5.c 第 2531-2532 行
if (mlx5_mmap(&context->uar[i], i, cmd_fd, page_size,
              context->shut_up_bf ? MLX5_UAR_TYPE_NC :
              MLX5_UAR_TYPE_REGULAR) == MAP_FAILED)
```

```
┌─────────────┬──────────────────────┬──────────────────────┬──────────────────┐
│ shut_up_bf  │       UAR 类型       │      mmap 命令       │     页表属性     │
│    值       │                      │                      │                  │
├─────────────┼──────────────────────┼──────────────────────┼──────────────────┤
│ 0 (默认)    │ MLX5_UAR_TYPE_REGULAR│ MLX5_IB_MMAP_ALLOC_WC│ NORMAL-NC        │
├─────────────┼──────────────────────┼──────────────────────┼──────────────────┤
│ 1           │ MLX5_UAR_TYPE_NC     │ MLX5_IB_MMAP_NC_PAGE │ DEVICE_nGnRnE    │
└─────────────┴──────────────────────┴──────────────────────┴──────────────────┘
```

内核侧处理
```c
// mlx5/main.c 第 2213-2219 行
switch (cmd) {
case MLX5_IB_MMAP_WC_PAGE:
case MLX5_IB_MMAP_ALLOC_WC:         // ← WC 路径
case MLX5_IB_MMAP_REGULAR_PAGE:
    prot = pgprot_writecombine(vma->vm_page_prot);  // → NORMAL-NC
    break;
case MLX5_IB_MMAP_NC_PAGE:          // ← NC 路径
    prot = pgprot_noncached(vma->vm_page_prot);      // → DEVICE_nGnRnE
    break;
}
```
对比结果

```
┌─────────┬──────────────┬─────────────────┐
│  环境   │  shut_up_bf  │      属性       │
├─────────┼──────────────┼─────────────────┤
│  Host   │   0 (默认)   │   NORMAL-NC     │
├─────────┼──────────────┼─────────────────┤
│ Guest   │    可能为 1  │ DEVICE_nGnRnE   │
└─────────┴──────────────┴─────────────────┘
```

验证
```shell
# 在 Host 上运行测试前：

# 检查环境变量
echo $MLX5_SHUT_UP_BF  # 如果没输出就是 unset，默认是 0

# 或者直接看 /proc 环境
cat /proc/$(pgrep -f ib_read_lat)/environ | tr '\0' '\n' | grep MLX5
```

如果 Host 上也是 DEVICE_nGnRnE，说明 Host 的 shut_up_bf 也是 1。

# host vs guest 的路径猜测

❯ 还需要分析一下在当前测试结果为前提下，host和guest分别是怎么配的？二者的完整流程

## 测试结果

| 环境 | 页表属性 | AttrIdx |
|------|----------|---------|
| Host | MEM/NORMAL-NC | NORMAL-NC |
| Guest | DEVICE/nGnRnE | DEVICE_nGnRnE |

---

## Host 侧完整流程（得到 NORMAL-NC）

### 1. 用户态选择 UAR 类型

文件: `providers/mlx5/mlx5.c`

```c
// 第 2506 行
context->shut_up_bf = get_shut_up_bf();  // 返回 0 (默认)

// 第 2531 行
if (mlx5_mmap(&context->uar[i], i, cmd_fd, page_size,
              context->shut_up_bf ? MLX5_UAR_TYPE_NC :  // 0 ? false
              MLX5_UAR_TYPE_REGULAR) == MAP_FAILED)      // ← 走这里
结果: MLX5_UAR_TYPE_REGULAR

### 2. 用户态选择 mmap 命令

```c
// 第 2208 行
offset = get_uar_mmap_offset(index, page_size,
    (uar_type == MLX5_UAR_TYPE_REGULAR_DYN) ? MLX5_IB_MMAP_ALLOC_WC :
    MLX5_MMAP_GET_REGULAR_PAGES_CMD);  // ← 走这里
```

```
mmap 命令: MLX5_MMAP_GET_REGULAR_PAGES_CMD = 0
```

### 3. 内核决定页表属性

文件: `drivers/infiniband/hw/mlx5/main.c`

```c
// 第 2213 行
switch (cmd) {
case MLX5_IB_MMAP_WC_PAGE:
case MLX5_IB_MMAP_ALLOC_WC:
case MLX5_IB_MMAP_REGULAR_PAGE:         // ← cmd=0 匹配这个
    prot = pgprot_writecombine(vma->vm_page_prot);  // → NORMAL-NC
    break;
case MLX5_IB_MMAP_NC_PAGE:
    prot = pgprot_noncached(vma->vm_page_prot);     // → DEVICE_nGnRnE
    break;
}
```

```
页表属性: pgprot_writecombine() → MT_NORMAL_NC
```

### Host 流程总结

```
shut_up_bf = 0 (默认)
      ↓
MLX5_UAR_TYPE_REGULAR
      ↓
MLX5_MMAP_GET_REGULAR_PAGES_CMD (cmd=0)
      ↓
pgprot_writecombine()
      ↓
MT_NORMAL_NC → MEM/NORMAL-NC ✓
```

## Guest 侧完整流程（得到 DEVICE_nGnRnE）

### 1. 用户态选择 UAR 类型

```c
context->shut_up_bf = get_shut_up_bf();  // 返回 1 (可能)
```

可能原因:

- Guest 里有 `MLX5_SHUT_UP_BF=1` 环境变量
- 或者 Guest 的 `get_shut_up_bf()` 返回 1

```c
if (mlx5_mmap(&context->uar[i], ..., MLX5_UAR_TYPE_NC))  // ← 走这里
```

### 2. 用户态选择 mmap 命令

```c
// 第 2194 行
if (uar_type == MLX5_UAR_TYPE_NC) {
    offset = get_uar_mmap_offset(index, page_size,
                     MLX5_MMAP_GET_NC_PAGES_CMD);  // ← cmd=3
}
```

```
mmap 命令: MLX5_MMAP_GET_NC_PAGES_CMD = 3
```

### 3. 内核决定页表属性

```c
switch (cmd) {
case MLX5_IB_MMAP_NC_PAGE:    // ← cmd=3 或 NC 类型会走这里
    prot = pgprot_noncached(vma->vm_page_prot);  // → DEVICE_nGnRnE
}
```

```
页表属性: pgprot_noncached() → MT_DEVICE_nGnRnE
```

### Guest 流程总结

```
shut_up_bf = 1 (或 MLX5_SHUT_UP_BF=1)
      ↓
MLX5_UAR_TYPE_NC
      ↓
MLX5_MMAP_GET_NC_PAGES_CMD (cmd=3)
      ↓
pgprot_noncached()
      ↓
MT_DEVICE_nGnRnE → DEVICE/nGnRnE ✓
```

## 对比总结

| 步骤 | Host | Guest |
|------|------|-------|
| shut_up_bf | 0 (默认) | 1 |
| UAR 类型 | REGULAR | NC |
| mmap 命令 | GET_REGULAR_PAGES_CMD (0) | GET_NC_PAGES_CMD (3) |
| 内核页表属性 | pgprot_writecombine() | pgprot_noncached() |
| AttrIdx | NORMAL-NC | DEVICE_nGnRnE |
| 写合并 | ✓ 允许 | ✗ 禁止 |

## 验证方法

在 Guest 里检查：

```bash
# 方法1: 看环境变量
echo $MLX5_SHUT_UP_BF

# 方法2: 在 rdma-core 代码里加打印
# mlx5.c 第 2531 行之前加:
printf("shut_up_bf = %d\n", context->shut_up_bf);
printf("uar_type = %s\n", context->shut_up_bf ? "NC" : "REGULAR");
```