// SPDX-License-Identifier: GPL-2.0
/*
 * User space page table query module
 *
 * This module allows querying PTE attributes for a user space virtual address
 * by walking the process's page tables. It supports both 4KB pages
 * and 2MB huge pages (section mappings).
 */

#include <linux/module.h>
#include <linux/mm.h>
#include <linux/sched.h>
#include <linux/printk.h>
#include <linux/pid.h>
#include <linux/slab.h>
#include <linux/io.h>

/* Module parameters */
static unsigned long target_va = 0x0UL;
static int target_pid = 0;

/* Page size for ARM64 4KB pages */
#define PAGE_SIZE_4K 4096UL

/*
 * ARM64 Memory Type definitions - Same logic as stage1 ptdump in kernel
 *
 * PTE_ATTRINDX(t) = (t << 2), stored in PTE bits [4:2]
 * So the actual value in PTE is: prot = raw_pte & PTE_ATTRINDX_MASK
 *
 * prot values match PTE_ATTRINDX(MT_*):
 *   PTE_ATTRINDX(MT_DEVICE_nGnRnE) = (3 << 2) = 12 = 0xc
 *   PTE_ATTRINDX(MT_DEVICE_nGnRE)  = (4 << 2) = 16 = 0x10
 *   PTE_ATTRINDX(MT_NORMAL_NC)      = (2 << 2) =  8 = 0x8
 *   PTE_ATTRINDX(MT_NORMAL)         = (0 << 2) =  0 = 0x0
 *   PTE_ATTRINDX(MT_NORMAL_TAGGED)  = (1 << 2) =  4 = 0x4
 */
#define PTE_ATTRINDX_MASK     GENMASK(4, 2)
#define PTE_ATTRINDX(n)      ((n) << 2)

/* MT_* values from memory.h */
#define MT_DEVICE_nGnRnE      3
#define MT_DEVICE_nGnRE       4
#define MT_NORMAL_NC           2
#define MT_NORMAL              0
#define MT_NORMAL_TAGGED      1

/*
 * Shareability (SH) bits are bits [9:8] of the PTE
 * SH = 00: Non-shareable
 * SH = 01: Reserved
 * SH = 10: Outer Shareable
 * SH = 11: Inner Shareable
 */
#define SH_MASK GENMASK(9, 8)
#define SH_SHIFT 8

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

static int __init usr_pte_query_init(void)
{
	struct task_struct *task;
	struct mm_struct *mm;
	pgd_t *pgd;
	p4d_t *p4d;
	pud_t *pud;
	pmd_t *pmd;
	pte_t *ptep, pte;
	unsigned long raw_hw_pte;
	unsigned long phys_addr;
	unsigned long prot;
	u8 sh;

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

	/* Check VMA first to verify this is a valid userspace mapping */
	{
		struct vm_area_struct *vma = find_vma(mm, target_va);
		if (!vma || target_va < vma->vm_start) {
			pr_err("No VMA found for VA 0x%lx\n", target_va);
			goto out_mmput;
		}
		pr_info("VMA: 0x%lx-0x%lx flags=0x%lx\n",
			vma->vm_start, vma->vm_end, vma->vm_flags);
	}

	/* Start page table walk from PGD */
	pgd = pgd_offset(mm, target_va);
	if (pgd_none(*pgd) || pgd_bad(*pgd)) {
		pr_err("usr_pte_query: PGD entry is invalid at VA 0x%lx\n", target_va);
		goto out_mmput;
	}

	/* Walk to P4D */
	p4d = p4d_offset(pgd, target_va);
	if (p4d_none(*p4d) || p4d_bad(*p4d)) {
		pr_err("usr_pte_query: P4D entry is invalid at VA 0x%lx\n", target_va);
		goto out_mmput;
	}

	/* Walk to PUD */
	pud = pud_offset(p4d, target_va);
	if (pud_none(*pud) || pud_bad(*pud)) {
		pr_err("usr_pte_query: PUD entry is invalid at VA 0x%lx\n", target_va);
		goto out_mmput;
	}

	/* Walk to PMD */
	pmd = pmd_offset(pud, target_va);
	if (pmd_none(*pmd)) {
		pr_err("usr_pte_query: PMD entry is unmapped at VA 0x%lx\n", target_va);
		goto out_mmput;
	}

	/* Check for 2MB huge page (section mapping in ARM64) */
	if (pmd_sect(*pmd)) {
		pr_info("Detected 2MB HugePage (PMD Section mapping)\n");

		raw_hw_pte = pmd_val(*pmd);

		/* Extract physical address from PMD (2MB block: bits [51:21]) */
		phys_addr = (raw_hw_pte & GENMASK_ULL(51, 21)) |
			    (target_va & (SZ_2M - 1));

		/* Extract prot = bits [4:2] AttrIdx */
		prot = raw_hw_pte & PTE_ATTRINDX_MASK;

		/* Extract Shareability [9:8] */
		sh = (raw_hw_pte >> SH_SHIFT) & 0x3;

		pr_info("-----------------------------------------\n");
		pr_info("PMD Level (2MB Block Mapping):\n");
		pr_info("  Raw PMD:        0x%016lx\n", raw_hw_pte);
		pr_info("  Physical Addr:  0x%016lx\n", phys_addr);
		pr_info("  AttrIdx:        %s\n", memattr_to_string(prot));
		pr_info("  SH [9:8]:      %u (%s)\n", sh,
			sh_to_string(sh));
		pr_info("-----------------------------------------\n");

		goto out_mmput;
	}

	if (pmd_bad(*pmd)) {
		pr_err("usr_pte_query: PMD entry is bad at VA 0x%lx\n", target_va);
		goto out_mmput;
	}

	/* Walk to PTE (4KB page) using physical address calculation */
	{
		/*
		 * Use pte_offset_kernel() instead of phys_to_virt().
		 * Reason: phys_to_virt() assumes the PTE page is in the linear
		 * mapping region. pte_offset_kernel() is the correct kernel API.
		 */
		ptep = pte_offset_kernel(pmd, target_va);

		pte = *ptep;

		if (pte_none(pte)) {
			pr_err("usr_pte_query: PTE is not mapped (page fault) at VA 0x%lx\n", target_va);
			goto out_mmput;
		}

		if (pte_special(pte)) {
			pr_info("Detected special mapping (vmalloc/mmio/ioremap)\n");
			raw_hw_pte = pte_val(pte);
			phys_addr = 0; /* Special mappings don't have RAM physical addresses */
			prot = raw_hw_pte & PTE_ATTRINDX_MASK;
			sh = (raw_hw_pte >> SH_SHIFT) & 0x3;

			pr_info("-----------------------------------------\n");
			pr_info("PTE Level (Special Mapping):\n");
			pr_info("  Raw PTE:        0x%016lx\n", raw_hw_pte);
			pr_info("  Physical Addr:   N/A (special mapping - I/O remap PFN)\n");
			pr_info("  AttrIdx:        %s\n", memattr_to_string(prot));
			pr_info("  SH [9:8]:       %u (%s)\n", sh,
				sh_to_string(sh));
			pr_info("-----------------------------------------\n");
			goto out_mmput;
		}

		raw_hw_pte = pte_val(pte);

		/* Extract physical address from PTE */
		phys_addr = (raw_hw_pte & GENMASK_ULL(51, 12)) | (target_va & (PAGE_SIZE_4K - 1));

		/* Extract prot = bits [4:2] AttrIdx */
		prot = raw_hw_pte & PTE_ATTRINDX_MASK;

		/* Extract Shareability [9:8] */
		sh = (raw_hw_pte >> SH_SHIFT) & 0x3;

		pr_info("-----------------------------------------\n");
		pr_info("PTE Level (4KB Page Mapping):\n");
		pr_info("  Raw PTE:        0x%016lx\n", raw_hw_pte);
		pr_info("  Physical Addr:  0x%016lx\n", phys_addr);
		pr_info("  AttrIdx:        %s\n", memattr_to_string(prot));
		pr_info("  SH [9:8]:      %u (%s)\n", sh,
				sh_to_string(sh));
		pr_info("-----------------------------------------\n");
	}

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
MODULE_VERSION("1.0");

module_init(usr_pte_query_init);
module_exit(usr_pte_query_exit);
