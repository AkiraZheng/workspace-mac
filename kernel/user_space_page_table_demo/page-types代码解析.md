page-types.c
	它通过 /proc/pid/pagemap 获取物理页框号（PFN），然后用这个PFN作为索引去查询 /proc/kpageflags，最终得到的是内核为这个物理页贴上的软件标签

地址区间信息来自 /proc/pid/maps

```c
static void parse_pid(const char *str)
{
    // 打开 /proc/pid/maps 文件
    sprintf(buf, "/proc/%d/maps", opt_pid);
    file = fopen(buf, "r");
    
    while (fgets(buf, sizeof(buf), file) != NULL) {
        // 解析 maps 文件中的每一行，获取 VMA 的起始和结束地址
        n = sscanf(buf, "%lx-%lx %c%c%c%c %llx %x:%x %lu",
               &vm_start, &vm_end, ...);
        
        // 存储 VMA 区间（按页对齐）
        pg_start[nr_vmas] = vm_start / page_size;
        pg_end[nr_vmas] = vm_end / page_size;
        nr_vmas++;
    }
}
```

/proc/pid/maps 文件已经包含了进程所有内存区间的虚拟地址范围（VMA），内核在维护进程地址空间时就已经计算好了这些信息。所以 page-types.c 没有进行完整的页表遍历。

所以papge-types.c实际做的工作是：

```
用户态程序 (page-types.c)
    ↓
读取 /proc/pid/maps  → 获得虚拟地址区间
    ↓
对每个区间，读取 /proc/pid/pagemap → 获得 PFN
    ↓
用 PFN 读取 /proc/kpageflags → 获得软件标志
    ↓
输出结果
```

真正执行了遍历页表操作的是`/proc/pid/pagemap`的时候会去遍历用户态页表，所以得想办法改造/proc/pid/pagemap，让他在遍历页表的时候把用户态页表中的叶子节点属性信息也给带出来：

```
内核遍历用户态页表
    ↓
从 mm_struct->pgd 开始（对应 TTBR0_EL1）
    ↓
逐级遍历: PGD → PUD → PMD → PTE
    ↓
从 PTE 中提取 PFN 和标志位
    ↓
填充到 /proc/pid/pagemap 文件中
```

------------------------------那么如何得到页表信息呢？------------------------------


// 内核源码中用于描述进程地址空间的核心结构体（简化版）
struct mm_struct {
    struct {
        pgd_t *pgd;  // 指向页全局目录（PGD）的指针，这是页表的根，可以通过这里来遍历到页表项的信息，以及他们的页表属性
        // ... 其他内存区域描述符
    };
    // ... 其他管理信息
};


一个页表项下，指向的地址空间区域的页表属性肯定都是一样的，比如4级页表最后一级的4KB页都是相同属性



## 用编写驱动的方式来dump出用户态页表

```
  功能：                                                                        
  - 支持 target_pid 和 target_va 两个模块参数                                   
  - 遍历页表：PGD → P4D → PUD → PMD → PTE                                       
  - 支持大页检测（pmd_sect 检测 2MB Section 映射）                              
  - 提取 PTE 的 AttrIdx（bits [4:2]）                                           
  - 打印物理地址                                                                
  - 输出 Memory Type 字符串                                                     
                                                                                
  文件2: /root/openeuler/kernel/usr_pt_query_Makefile`                          
                                                                                
  编译步骤：                                                                    
  cd /root/openeuler/kernel                                                     
  make -f usr_pte_query_Makefile                                                
                                                                                
  使用方式：                                                                    
  # 加载模块                                                                    
  insmod usr_pte_query.ko target_pid=<pid> target_va=0x<your_va>                
                                                                                
  # 查看输出                                                                    
  dmesg | tail -30                                                              
                                                                                
  # 卸载                                                                        
  rmmod usr_pte_query                                                           
                                                                                
  输出示例：                                                                    
  =========================================                                     
  usr_pte_query: PID=1234, VA=0x7fff8c000000                                    
  =========================================                                     
  -----------------------------------------                                     
  PTE Level (4KB Page Mapping):                                                 
    Raw PTE:        0x00000000c00843e3                                          
    Physical Addr:   0x0080000000000                                            
    AttrIdx [4:2]:   3 (MEM/NORMAL)                                             
  -----------------------------------------                                     
                                                                                
  或大页情况：                                                                  
  -----------------------------------------                                     
  PMD Level (2MB Block Mapping):                                                
    Raw PMD:     0x00000000c00843e3                                             
    Physical Addr: 0x0080000000000                                              
    AttrIdx [4:2]:   1 (DEVICE/nGnRE)                                           
  -----------------------------------------
```