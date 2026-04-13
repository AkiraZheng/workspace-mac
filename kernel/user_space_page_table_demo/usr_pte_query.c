// SPDX-License-Identifier: GPL-2.0
/*
 * User space page table query module
 *
 * This module allows querying PTE attributes for a user space virtual address
 * by walking the process's page tables using the generic kernel page walk
 * framework (walk_page_range). It supports both 4KB pages and 2MB huge
 * pages (section mappings).
 */

#include <linux/module.h>
#include <linux/mm.h>
#include <linux/pagewalk.h>
#include <linux/sched.h>
#include <linux/printk.h>
#include <linux/pid.h>

/* Module parameters */
static unsigned long target_va = 0x0UL;
static int target_pid = 0;

/*
 * ARM64 Memory Type definitions - Same logic as stage1 ptdump in kernel
 *
 * prot values match PTE_ATTRINDX(MT_*):
 *   PTE_ATTRINDX(MT_DEVICE_nGnRnE) = (3 << 2) = 12 = 0xc
 *   PTE_ATTRINDX(MT_DEVICE_nGnRE)  = (4 << 2) = 16 = 0x10
 *   PTE_ATTRINDX(MT_NORMAL_NC)      = (2 << 2) =  8 = 0x8
 *   PTE_ATTRINDX(MT_NORMAL)         = (0 << 2) =  0 = 0x0
 *   PTE_ATTRINDX(MT_NORMAL_TAGGED)  = (1 << 2) =  4 = 0x4
 *
 * Note: PTE_ATTRINDX_MASK and PTE_ATTRINDX are defined in asm/pgtable-hwdef.h
 * MT_* values are defined in asm/memory.h
 */

/* SH bits are bits [9:8] of the PTE */

/*
 * Shareability (SH) bits are bits [9:8] of the PTE
 * SH = 00: Non-shareable
 * SH = 01: Reserved
 * SH = 10: Outer Shareable
 * SH = 11: Inner Shareable
 */
#define SH_SHIFT 8

/* Result structure to collect PTE info during walk */
struct pte_query_result {
	unsigned long target_va;
	unsigned long raw_pte;
	unsigned long phys_addr;
	unsigned long prot;
	u8 sh;
	bool found;
	bool is_huge_page;  /* true if PMD section mapping */
	bool is_special;    /* true if special mapping (vmalloc/mmio/ioremap) */
};

/*
 * Same logic as dump_prot() in arch/arm64/mm/ptdump.c:
 * prot = raw_pte & PTE_ATTRINDX_MASK, then match against PTE_ATTRINDX(MT_*)
 */
static const char *memattr_to_string(unsigned long prot)
{
	/* Match stage1 pte_bits[] order - first match wins */
	if ((prot & PTE_ATTRINDX_MASK) == PTE_ATTRINDX(MT_DEVICE_nGnRnE))
		return "DEVICE/nGnRnE";
	if ((prot & PTE_ATTRINDX_MASK) == PTE_ATTRINDX(MT_DEVICE_nGnRE))
		return "DEVICE/nGnRE";
	if ((prot & PTE_ATTRINDX_MASK) == PTE_ATTRINDX(MT_NORMAL_NC))
		return "MEM/NORMAL-NC";
	if ((prot & PTE_ATTRINDX_MASK) == PTE_ATTRINDX(MT_NORMAL))
		return "MEM/NORMAL";
	if ((prot & PTE_ATTRINDX_MASK) == PTE_ATTRINDX(MT_NORMAL_TAGGED))
		return "MEM/NORMAL-TAGGED";
	return "UNKNOWN";
}

static const char *sh_to_string(u8 sh)
{
	switch (sh) {
	case 0:
		return "Non-shareable";
	case 1:
		return "Reserved";
	case 2:
		return "Outer Shareable";
	case 3:
		return "Inner Shareable";
	default:
		return "UNKNOWN";
	}
}

/* PMD entry callback - check for 2MB huge page (section mapping) */
static int pmd_callback(pmd_t *pmd, unsigned long addr,
			unsigned long next, struct mm_walk *walk)
{
	struct pte_query_result *result = walk->private;

	if (pmd_none(*pmd) || pmd_bad(*pmd))
		return -EFAULT;

	if (pmd_sect(*pmd)) {
		/* 2MB HugePage (section mapping) */
		result->found = true;
		result->is_huge_page = true;
		result->is_special = false;
		result->raw_pte = pmd_val(*pmd);
		/* PMD section: bits [51:21] for 2MB aligned address */
		result->phys_addr = (result->raw_pte & GENMASK_ULL(51, 21)) |
				     (result->target_va & (SZ_2M - 1));
		result->prot = result->raw_pte & PTE_ATTRINDX_MASK;
		result->sh = (result->raw_pte >> SH_SHIFT) & 0x3;
		return 1;  /* stop walking */
	}

	return 0;  /* continue to PTE level */
}

/* PTE entry callback - handle 4KB page mapping */
static int pte_callback(pte_t *pte, unsigned long addr,
			unsigned long next, struct mm_walk *walk)
{
	struct pte_query_result *result = walk->private;
	pte_t pte_entry;

	/* Only process the target address */
	if (addr != result->target_va)
		return 0;

	pte_entry = ptep_get_lockless(pte);

	if (pte_none(pte_entry)) {
		result->found = false;
		return -EFAULT;
	}

	result->found = true;
	result->is_huge_page = false;

	if (pte_special(pte_entry)) {
		/*
		 * Special mapping (vmalloc/mmio/ioremap).
		 * The PFN in this PTE is an I/O remap address, NOT a RAM
		 * physical address. Do NOT use it for stage-2 lookup.
		 */
		pr_info("Detected special mapping (vmalloc/mmio/ioremap)\n");
		result->is_special = true;
		result->phys_addr = 0;
		result->raw_pte = pte_val(pte_entry);
	} else {
		result->is_special = false;
		result->raw_pte = pte_val(pte_entry);
		result->phys_addr = (result->raw_pte & GENMASK_ULL(51, 12)) |
				     (result->target_va & (PAGE_SIZE - 1));
	}

	result->prot = result->raw_pte & PTE_ATTRINDX_MASK;
	result->sh = (result->raw_pte >> SH_SHIFT) & 0x3;

	return 1;  /* stop walking */
}

static const struct mm_walk_ops query_walk_ops = {
	.pmd_entry = pmd_callback,
	.pte_entry = pte_callback,
};

static int __init usr_pte_query_init(void)
{
	struct task_struct *task;
	struct mm_struct *mm;
	struct pte_query_result result;
	int err;

	/* Find the target task */
	task = pid_task(find_vpid(target_pid), PIDTYPE_PID);
	if (!task) {
		pr_err("usr_pte_query: PID %d not found\n", target_pid);
		return -ESRCH;
	}

	/* Get the mm_struct (memory descriptor) */
	mm = get_task_mm(task);
	if (!mm) {
		pr_err("usr_pte_query: PID %d has no mm (kernel thread?)\n", target_pid);
		return -ESRCH;
	}

	pr_info("=========================================\n");
	pr_info("usr_pte_query: PID=%d, VA=0x%lx\n", target_pid, target_va);
	pr_info("=========================================\n");

	/* Initialize result */
	result.target_va = target_va;
	result.found = false;
	result.is_huge_page = false;
	result.is_special = false;

	/*
	 * Use walk_page_range() - the generic kernel page table walk framework.
	 * This handles:
	 *   - Proper locking (mmap_read_lock)
	 *   - Correct PTE address calculation (pte_offset_map with kmap_local_page if needed)
	 *   - RCU protection
	 *   - Walking through all page table levels
	 */
	err = walk_page_range(mm, target_va, target_va + PAGE_SIZE,
			     &query_walk_ops, &result);

	if (err < 0) {
		pr_err("usr_pte_query: page table walk failed: %d\n", err);
		goto out_mmput;
	}

	if (!result.found) {
		pr_err("usr_pte_query: PTE not found at VA 0x%lx\n", target_va);
		goto out_mmput;
	}

	/* Output the result */
	pr_info("-----------------------------------------\n");
	if (result.is_huge_page) {
		pr_info("PMD Level (2MB Block Mapping):\n");
	} else if (result.is_special) {
		pr_info("PTE Level (Special Mapping - mmio/vmalloc/ioremap):\n");
	} else {
		pr_info("PTE Level (4KB Page Mapping):\n");
	}
	pr_info("  Raw PTE:        0x%016lx\n", result.raw_pte);
	if (result.is_special) {
		pr_info("  Physical Addr:   N/A (special mapping - I/O remap PFN)\n");
	} else {
		pr_info("  Physical Addr:  0x%016lx\n", result.phys_addr);
	}
	pr_info("  AttrIdx:        %s\n", memattr_to_string(result.prot));
	pr_info("  SH [9:8]:      %u (%s)\n", result.sh, sh_to_string(result.sh));
	pr_info("-----------------------------------------\n");

out_mmput:
	mmput(mm);
	return 0;
}

static void __exit usr_pte_query_exit(void)
{
	pr_info("usr_pte_query: Module unloaded\n");
}

module_param(target_va, ulong, 0644);
MODULE_PARM_DESC(target_va, "Virtual address to query PTE for (in hex)");

module_param(target_pid, int, 0644);
MODULE_PARM_DESC(target_pid, "PID of the process to query");

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Claude");
MODULE_DESCRIPTION("Query user space PTE attributes for debugging");
MODULE_VERSION("2.0");

module_init(usr_pte_query_init);
module_exit(usr_pte_query_exit);
