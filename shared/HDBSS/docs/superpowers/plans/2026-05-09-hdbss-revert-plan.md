# HDBSS Revert Plan

记录需要revert的HDBSS相关commits，共8个。

## Revert顺序（从最新到最老）

每个commit单独revert并立即commit。

### Commit 1
- **Hash**: b1d8169dd540
- **Subject**: !17748  fix bug in hdbss
- **Merge commit**: 是 (需要 -m 1)
- **Files**: arch/arm64/kvm/arm.c

### Commit 2
- **Hash**: 00c93102b328
- **Subject**: KVM: arm64: fix memory leak in HDBSS
- **Merge commit**: 否
- **Files**: arch/arm64/kvm/arm.c

### Commit 3
- **Hash**: a5e3c939fbb1
- **Subject**: KVM: arm64: do not support hdbss in nvhe
- **Merge commit**: 否
- **Files**: arch/arm64/kvm/arm.c

### Commit 4
- **Hash**: fe4fa7481191
- **Subject**: !15754 v3  Support the FEAT_HDBSS introduced in Armv9.5
- **Merge commit**: 是 (需要 -m 1)
- **Files**: arch/arm64/Kconfig, arch/arm64/configs/openeuler_defconfig, arch/arm64/include/asm/cpufeature.h, arch/arm64/include/asm/esr.h, arch/arm64/include/asm/kvm_arm.h, arch/arm64/include/asm/kvm_host.h, arch/arm64/include/asm/kvm_mmu.h, arch/arm64/include/asm/kvm_pgtable.h, arch/arm64/include/asm/sysreg.h, arch/arm64/kvm/arm.c, arch/arm64/kvm/handle_exit.c, arch/arm64/kvm/hyp/pgtable.c, arch/arm64/kvm/hyp/vhe/switch.c, arch/arm64/kvm/hyp/vhe/sysreg-sr.c, arch/arm64/kvm/mmu.c, arch/arm64/kvm/reset.c, arch/arm64/tools/sysreg, include/linux/kvm_host.h, include/uapi/linux/kvm.h, tools/include/uapi/linux/kvm.h

### Commit 5
- **Hash**: 8d2e1e3b26a9
- **Subject**: arm64/config: add config to control whether enable HDBSS feature
- **Merge commit**: 否
- **Files**: arch/arm64/Kconfig, arch/arm64/configs/openeuler_defconfig, arch/arm64/include/asm/cpufeature.h, arch/arm64/include/asm/kvm_host.h, arch/arm64/include/asm/kvm_mmu.h, arch/arm64/kvm/arm.c, include/linux/kvm_host.h

### Commit 6
- **Hash**: 6d60015590c3
- **Subject**: arm64/kvm: support to handle the HDBSSF event
- **Merge commit**: 否
- **Files**: arch/arm64/include/asm/esr.h, arch/arm64/kvm/arm.c, arch/arm64/kvm/handle_exit.c, arch/arm64/kvm/hyp/vhe/switch.c, arch/arm64/kvm/hyp/vhe/sysreg-sr.c, arch/arm64/kvm/reset.c

### Commit 7
- **Hash**: bd6106e348d7
- **Subject**: arm64/kvm: using ioctl to enable/disable the HDBSS feature
- **Merge commit**: 否
- **Files**: arch/arm64/include/asm/kvm_host.h, arch/arm64/kvm/arm.c, include/uapi/linux/kvm.h

### Commit 8
- **Hash**: 16ab2a2fee8b
- **Subject**: arm64/sysreg: add HDBSS related register information
- **Merge commit**: 否
- **Files**: arch/arm64/include/asm/esr.h, arch/arm64/include/asm/kvm_arm.h, arch/arm64/tools/sysreg

## 执行要求

1. 每个commit单独revert
2. Merge commit使用 `-m 1` flag
3. revert后立即commit，commit message格式：
   ```
   Revert: <original subject>
   
   This reverts HDBSS implementation as part of v4 redesign.
   ```
4. 每完成一个revert commit后停下来，让用户确认

## 预期结果

完成8个revert后，HDBSS_V4_2分支应该回到最初状态（不包含任何HDBSS代码），并且有8个新的revert commit。