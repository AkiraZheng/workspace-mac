Host 侧 mmap 路径

// mlx5.c 第 2531-2532 行
if (mlx5_mmap(&context->uar[i], i, cmd_fd, page_size,
              context->shut_up_bf ? MLX5_UAR_TYPE_NC :
              MLX5_UAR_TYPE_REGULAR) == MAP_FAILED)

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

在 Host 上运行测试前：

# 检查环境变量
echo $MLX5_SHUT_UP_BF  # 如果没输出就是 unset，默认是 0

# 或者直接看 /proc 环境
cat /proc/$(pgrep -f ib_read_lat)/environ | tr '\0' '\n' | grep MLX5

如果 Host 上也是 DEVICE_nGnRnE，说明 Host 的 shut_up_bf 也是 1。