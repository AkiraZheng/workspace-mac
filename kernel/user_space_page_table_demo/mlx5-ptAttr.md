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


# 路径自验证

一般 SMMU 设备的操作流程是这样的：

```
  CPU写命令到内存队列
          │                                                                     
          ▼
  写Doorbell寄存器 -- 此时还是 mmu 操作(通知SMMU)                                                   
          │       
          ▼
  SMMU读取命令
          │                                                                     
          ▼
  SMMU执行命令 (如TLB invalidate)                                               
          │       
          ▼
  写回Sync响应 (如果需要)
```

## 用户态

在用户态mlx5中`./rdma-core/providers/mlx5/mlx5.c`，是通过`env = getenv("MLX5_SHUT_UP_BF");`环境变量来确定使用什么类型属性。

```c
static int get_shut_up_bf(void)
{
    //...
    env = getenv("MLX5_SHUT_UP_BF");
    //...
}

static int mlx5_set_context(struct mlx5_context *context,
			    struct mlx5_ib_alloc_ucontext_resp *resp,
			    bool is_import)
{
    //...
        context->shut_up_bf = get_shut_up_bf();
		if (mlx5_mmap(&context->uar[i], i, cmd_fd, page_size,
			      context->shut_up_bf ? MLX5_UAR_TYPE_NC :
			      MLX5_UAR_TYPE_REGULAR) == MAP_FAILED) {
			context->uar[i].reg = NULL;
    //...
}

void *mlx5_mmap(struct mlx5_uar_info *uar, int index, int cmd_fd, int page_size,
		int uar_type)
{
	off_t offset;

	if (uar_type == MLX5_UAR_TYPE_NC) {
		offset = get_uar_mmap_offset(index, page_size,
					     MLX5_MMAP_GET_NC_PAGES_CMD);
		uar->reg = mmap(NULL, page_size, PROT_WRITE, MAP_SHARED,
				       cmd_fd, offset); //这里就会通过系统调用，把属性配下去，offset 编码了 mmap 命令
		if (uar->reg != MAP_FAILED) {
			uar->type = MLX5_UAR_TYPE_NC;
			goto out;
		}
	}

	/* Backward compatibility for legacy kernels that don't support
	 * MLX5_MMAP_GET_NC_PAGES_CMD mmap command.
	 */
	offset = get_uar_mmap_offset(index, page_size,
				     (uar_type == MLX5_UAR_TYPE_REGULAR_DYN) ?
				     MLX5_IB_MMAP_ALLOC_WC :
				     MLX5_MMAP_GET_REGULAR_PAGES_CMD);
	uar->reg = mmap(NULL, page_size, PROT_WRITE, MAP_SHARED,
			cmd_fd, offset); //这里就会通过系统调用，把属性配下去，offset 编码了 mmap 命令
	if (uar->reg != MAP_FAILED)
		uar->type = MLX5_UAR_TYPE_REGULAR;

out:
	return uar->reg;
}
```

```
  ┌────────┬─────────┬───────────────────────┬────────────────┬───────────┐     
  │ shut_u │  UAR    │       mmap 命令       │    内核处理    │ 页表属性  │ 
  │  p_bf  │  类型   │                       │                │           │     
  ├────────┼─────────┼───────────────────────┼────────────────┼───────────┤ 
  │ 0      │ REGULAR │ MLX5_MMAP_GET_REGULAR │ pgprot_writeco │ NORMAL-NC │ 
  │        │         │ _PAGES_CMD (0)        │ mbine()        │           │     
  ├────────┼─────────┼───────────────────────┼────────────────┼───────────┤ 
  │ 0      │ REGULAR │ MLX5_IB_MMAP_ALLOC_WC │ pgprot_writeco │ NORMAL-NC │     
  │        │ _DYN    │  (6)                  │ mbine()        │           │     
  ├────────┼─────────┼───────────────────────┼────────────────┼───────────┤ 
  │ 1      │ NC      │ MLX5_MMAP_GET_NC_PAGE │ pgprot_noncach │ DEVICE_nG │     
  │        │         │ S_CMD (3)             │ ed()           │ nRnE      │     
  └────────┴─────────┴───────────────────────┴────────────────┴───────────┘
```

NC 延迟最低，但 REGULAR 在多数实际工作负载中因缓存收益往往更好。环境变量 MLX5_SHUT_UP_BF 主要用于特定调试或低延迟优化场景。

## 内核态-stage1

上面是用户态下发 cmd 的流程，接着 mmap 系统调用后就会到内核态进行处理，内核态代码可以看 mlx5 驱动代码`./openeuler/kernel/drivers/infiniband/hw/mlx5/main.c`

```c
static const struct ib_device_ops mlx5_ib_dev_ops = {
    // ...
    .mmap = mlx5_mmap,
    // ...
}
```

所以实际上驱动执行`mmap`系统调用，会调用内核态的`mlx5_ib_mmap()`，属性也是在这里配置下去的

```c
static int mlx5_ib_mmap(struct ib_ucontext *ibcontext, struct vm_area_struct *vma)
{
	struct mlx5_ib_ucontext *context = to_mucontext(ibcontext);
	struct mlx5_ib_dev *dev = to_mdev(ibcontext->device);
	unsigned long command;
	phys_addr_t pfn;

	command = get_command(vma->vm_pgoff);
	switch (command) {
	case MLX5_IB_MMAP_WC_PAGE:
	case MLX5_IB_MMAP_ALLOC_WC:
		if (!dev->wc_support)
			return -EPERM;
		fallthrough;
	case MLX5_IB_MMAP_NC_PAGE:
	case MLX5_IB_MMAP_REGULAR_PAGE:
		return uar_mmap(dev, command, vma, context);//全都路由到同一个地方执行 uar_mmap

	//...

	return 0;
}

static int uar_mmap(struct mlx5_ib_dev *dev, enum mlx5_ib_mmap_cmd cmd,
		    struct vm_area_struct *vma,
		    struct mlx5_ib_ucontext *context)
{
	//...

	switch (cmd) {
	case MLX5_IB_MMAP_WC_PAGE:
	case MLX5_IB_MMAP_ALLOC_WC:
	case MLX5_IB_MMAP_REGULAR_PAGE:
		/* For MLX5_IB_MMAP_REGULAR_PAGE do the best effort to get WC */
		prot = pgprot_writecombine(vma->vm_page_prot);
		break;
	case MLX5_IB_MMAP_NC_PAGE:
		prot = pgprot_noncached(vma->vm_page_prot);
		break;
	default:
		return -EINVAL;
	}

	//...

err:
	if (!dyn_uar)
		return err;

	mlx5_cmd_uar_dealloc(dev->mdev, idx, context->devx_uid);

free_bfreg:
	mlx5_ib_free_bfreg(dev, bfregi, bfreg_dyn_idx);

	return err;
}
```

其中，内核态配置属性时，可能会因为场景的不同而修改页表属性
- 其中host侧测试的话，通过io_remap_pfn_range 建立的是系统页表（VA → host PA），属性直接用户态的vm_page_prot，不会改变。
- guest侧测试的话，通过VFIO 透传，只有 stage1 会走 io_remap_pfn_range，stage 2页表映射时，有可能就会修改页表属性。具体看 stage 2的解析

完整的调用栈为：

```text
  用户态（libmlx5）

  应用程序 (ib_read_lat / ib_write_lat)
      ↓
      post_send_db() in qp.c
      ↓ (mmap 系统调用)
      mmap(NULL, size, PROT_WRITE, MAP_SHARED, fd, offset)

  用户态 mlx5 库

  Step 1: mlx5_mmap() 决定 mmap 命令
  mlx5_mmap(uar, index, cmd_fd, page_size, uar_type)
      │
      ├─ if (uar_type == MLX5_UAR_TYPE_NC)
      │       ↓
      │   get_uar_mmap_offset(..., MLX5_MMAP_GET_NC_PAGES_CMD)  // cmd=3
      │
      └─ else (REGULAR / REGULAR_DYN)
              ↓
          get_uar_mmap_offset(...,
              (uar_type == MLX5_UAR_TYPE_REGULAR_DYN) ?
                  MLX5_IB_MMAP_ALLOC_WC :         // cmd=6
                  MLX5_MMAP_GET_REGULAR_PAGES_CMD)  // cmd=0
      │
      ↓
  mmap(fd, offset)  ← 系统调用，offset 编码了 mmap 命令

  内核态（mlx5 驱动）

  Step 2: mlx5_ib_mmap() 处理 mmap
  sys_mmap() → mlx5_ib_mmap()
      │
      ├─ get_command(vma->vm_pgoff)  // 从 offset 解码出命令
      │
      └─ switch(cmd) {
             case MLX5_IB_MMAP_WC_PAGE:
             case MLX5_IB_MMAP_ALLOC_WC:        // cmd=6
             case MLX5_IB_MMAP_REGULAR_PAGE:
                     prot = pgprot_writecombine()  // → NORMAL-NC

             case MLX5_IB_MMAP_NC_PAGE:         // cmd=3
                     prot = pgprot_noncached()      // → DEVICE_nGnRnE
         }
      | 
      └── vma->vm_page_prot = prot              // ⬅️  关键：属性写入 VMA
      │
      ↓
  io_remap_pfn_range(vma, addr, pfn, size, prot)
      │
      ↓
      创建 VMA，设置页表属性
      └── io_remap_pfn_range() 或 remap_pfn_range()
      └── Set PageTabl 属性                 :                               
          ├── _PAGE_CACHE_MODE = pgprot 解析后的 cache mode
          └── PTE attributes 由 vma->vm_page_prot 决定 

  Step3：page fault 时创建 PTE（vm_page_prot 在 mmap 时确定后，page fault 创建 PTE 时直接使用）                                            
                                                                   
  VM 运行访问 UAR 地址 → 页故障 → handle_mm_fault()
  └── __handle_mm_fault()                                                       
      └── create_pte()
          └── set_pte_at()                                                      
              └── arch-specific: 转换 vm_page_prot → hardware PTE
                  ├── pgprot_noncached() → ATTRINDX(DEVICE_nGnRnE) = 0xc        
                  └── pgprot_writecombine() → ATTRINDX(NORMAL_NC) = 0x8  
```

## 内核态-stage2

VFIO/IOMMU 会硬编码配置成 Device_nGnRE，而且 ARM Stage2  不是通过`io_remap_pfn_range`设置的属性，而是通过`arm_smmu_map_pages`设置的。

- Stage-1 建立：Guest 进程调用 mmap() 时，用户态触发

    ```text
      Guest 用户空间
        └── mmap()  // 用户空间调用
            ⬇️ 
        Guest 内核 (陷入内核)
        └── mmap_region()
        └── io_remap_pfn_range()        // 建立 GVA → GPA (Stage-1)
            └── set_pte()                  // 只设置 Stage-1
    ```

- Stage-2 建立：QEMU 启动 VM 时，QEMU 模拟 VFIO 设备

    ```text
        QEMU (用户空间)                                                               
        └── vfio_iommu_map_dma(iova=GPA, paddr=HPA, size=..., prot=...)               
            ⬇️  [ioctl 陷入内核]                                                       
                                                                                        
        内核 VFIO                                                                     
        └── drivers/vfio/vfio_iommu_type1.c:1787                                      
            └── iommu_map(d->domain, iova, paddr, size, prot | IOMMU_CACHE,
        GFP_KERNEL)                                                                   
                ⬇️                              
            IOMMU Core (iommu.c)                                                      
                └── iommu_map() -> __iommu_map()                
                    └── ops->map_pages()  // d->domain->ops = arm_smmu_ops，[.map_pages		= arm_smmu_map_pages,]
                        ⬇️                      
                    ARM SMMU v3                                                       
                    └── drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c:3484
                        └── arm_smmu_map_pages()                                      
                            └── ops->map_pages()  // ops = io_pgtable_ops，【.map_pages	= arm_lpae_map_pages,】
                                ⬇️                                                     
                            ARM LPAE io-pgtable
                            └── drivers/iommu/io-pgtable-arm.c:546                    
                                └── arm_lpae_map_pages()
                                    └── arm_lpae_prot_to_pte()  // ← 关键！           
                                        ⬇️                                             
                                    写 SMMU Stream Table Entry (STE)
    ```

```c
static int vfio_iommu_map(struct vfio_iommu *iommu, dma_addr_t iova,
			  unsigned long pfn, long npage, int prot)
{
	struct vfio_domain *d;
	int ret;

	list_for_each_entry(d, &iommu->domain_list, next) {
		ret = iommu_map(d->domain, iova, (phys_addr_t)pfn << PAGE_SHIFT,
				npage << PAGE_SHIFT, prot | IOMMU_CACHE,
				GFP_KERNEL);
		...
	}

	...
}

 static arm_lpae_iopte arm_lpae_prot_to_pte(struct arm_lpae_io_pgtable *data, 
 int prot)//这里的 prot 参数由 VFIO 传递的                                             
 {                                                                             
     if (data->iop.fmt == ARM_64_LPAE_S2 || data->iop.fmt == ARM_32_LPAE_S2) {
         if (prot & IOMMU_MMIO) {                                              
             pte |= ARM_LPAE_PTE_MEMATTR_DEV;        // = 0x1 << 2 =           Device_nGnRE                           
         } else if (prot & IOMMU_CACHE) {                                      
             if (data->iop.cfg.quirks & IO_PGTABLE_QUIRK_ARM_S2FWB)
                 pte |= ARM_LPAE_PTE_MEMATTR_FWB_WB; // = 0x6 << 2 = Normal FWB
             else                        
                 pte |= ARM_LPAE_PTE_MEMATTR_OIWB;  // = 0xf << 2 = Normal OIWB
         } else {                       
             pte |= ARM_LPAE_PTE_MEMATTR_NC;         // = 0x5 << 2 = NC        
         }                              
     }                                                                         
     ...                                                                       
 }  
```



```text
  QEMU 启动时做了什么？
  ├── 解析命令行: -device vfio-pci,host=0000:03:00.0                            
  ├── 获取设备 BAR 信息 (lspci 或 sysfs)                                        
  ├── 计算 UAR 的 GPA 范围: 例如 0x4000000000 - 0x407FFFFFFF (128MB)            
  └── 调用 vfio_iommu_map_dma(GPA=0x4000000000, HPA=0x..., size=128MB)          
      └── SMMU 建立 GPA → HPA 映射 (整个 128MB 区域一次建立)                    
                                                                                
  所以当 Guest 用户态调用 mmap() 时，对应的 GPA → HPA                           
  映射已经存在了，不需要再触发 arm_smmu_map。
```

```text
  Step4：MemAttr 到 Stage-2 PTE 的映射

  iommu_map() → arm_smmu_map() → __arm_smmu_map_sg() → 写 STE/CD → SMMU 硬件
                                                                                
  Stage-2 PTE (ARM64)
  ┌────────────────────────────────────────────────────┐                        
  │  Bits 63:52 │ Bits 51:16          │ Bits 15:0    │
  ├────────────────────────────────────────────────────┤                        
  │  Reserved   │  Output Address (OA) │ Attributes    │                        
  └────────────────────────────────────────────────────┘                        
                       ↓                                                        
          MemAttr 在 bits [5:2] (与 Stage-1 类似)
                                                                                
          MemAttr 值:
          - 0x1 = Device_nGnRE (IOMMU 默认用于 MMIO)                            
          - 0xf = Normal (用于 RAM)                                             

```

## ARM 综合 stage1 && stage2 综合页表属性

ARM 架构规范定义属性组合规则，并在硬件中实现。

软件配置页表属性，硬件执行属性综合：

```text
┌─────────────────┐        ┌─────────────────┐
│  Stage-1 PTE   │        │                 │
│  MemAttr = A   │───────▶│  属性组合逻辑    │──────▶ 最终属性
│                 │        │  (硬件实现)     │
│  Stage-2 PTE    │        │                 │
│  MemAttr = B   │        │                 │
└─────────────────┘        └─────────────────┘
```

属性组合规则（硬件查表）：

| Stage-1 | Stage-2 | 最终结果 |
|---------|---------|----------|
| Normal | Normal | Normal（按规则合并 Cache/Share 属性） |
| Device | 任意 | Device（最保守胜出） |
| 任意 | Device | Device（最保守胜出） |
| NC/Uncached | 任意 | NC（最保守胜出） |

软件能控制与不能控制的边界：

| 软件能控制的 | 软件不能控制的 |
|--------------|----------------|
| Stage-1 属性（通过 pgprot） | 属性组合规则（硬件固定） |
| Stage-2 属性（通过 IOMMU/VFIO） | 硬件实现细节 |
| IOMMU_DOMAIN 类型 | |

关键点：

1. 软件配置：通过 pgprot_*() 选择 Stage-1 属性，通过 VFIO/IOMMU 选择 Stage-2 属性

2. 硬件执行：MMU/SMMU 遍历页表时，按 ARM 规范自动组合属性

3. 组合结果：对设备来说只看到最终属性，对软件透明

解决性能问题的关键在于，软件层面上需要同时控制 Stage-1 和 Stage-2 的属性，让它们的组合结果是期望的属性（如 NORMAL_NC）。

如果 VFIO 配置成 IOMMU_CACHE（Normal），即使 Stage-1 是 Device_nGnRnE，最终也是 Device_nGnRnE（Device 胜出）。

如果希望最终属性是 NORMAL_NC（允许写合并），需要：
- Stage-1 = NORMAL_NC（允许 WC）
- Stage-2 = Normal（不过度限制）

但 VFIO/IOMMU 默认不使用 IOMMU_MMIO，因为它无法区分区域是 MMIO 还是普通内存，这是 VFIO 的设计问题。

## 总结

- Host：mmap → vm_page_prot → page fault → io_remap_pfn_range → 按用户态 prot 
  设置属性                                                                      
- Guest Stage-1（Guest 系统页表）：mmap → vm_page_prot → page fault →
  io_remap_pfn_range → 按用户态 prot                                            
- Guest Stage-2（KVM 虚拟化页表）：完全由 VFIO/IOMMU driver 控制，与用户态
  prot 无关 