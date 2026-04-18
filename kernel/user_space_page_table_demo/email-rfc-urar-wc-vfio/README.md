# RFC: Enable Write-Combining UAR Mappings for VFIO Passthrough

## Summary

This RFC proposes an opt-in mechanism to enable write-combining (WC) UAR
(User Access Region) mappings for mlx5 devices passed through via VFIO
on arm64, restoring BlueFlame (BF) doorbell performance in trusted VMs.

## Problem

On bare-metal, mlx5 UAR doorbell mappings use write-combining (WC),
allowing BF doorbells with optimal latency (~2.45 usec).

Under VFIO passthrough on arm64:
- UAR mappings are forced to non-cached/device attributes
- BF is disabled (bf_reg_size == 0, wc_support == false)
- Latency degrades to ~2.95 usec (~0.5 usec overhead)

## Root Cause

1. **VFIO** (`vfio_pci_core_mmap` line 1889):
   ```c
   vma->vm_page_prot = pgprot_noncached(vma->vm_page_prot);
   ```

2. **mlx5** (`mlx5_ib_test_wc`):
   ```c
   if (mlx5_core_is_pf(dev->mdev))  // PF only!
       dev->wc_support = arch_can_pci_mmap_wc();
   return 0;  // VF exits here without wc_support
   ```

## Solution

Two-patch RFC:

### PATCH 1/2: VFIO - allow_wc_bar module parameter
- Add opt-in mechanism for WC mapping
- Disabled by default
- Requires explicit: `echo 1 > /sys/module/vfio_pci/parameters/allow_wc_bar`

### PATCH 2/2: mlx5 - force_wc_vf module parameter
- Allow WC support for VF when VFIO WC mapping is available
- Experimental, for trusted environments only
- Requires: `echo 1 > /sys/module/mlx5_ib/parameters/force_wc_vf`

## Usage

```bash
# Host: Load modules with experimental options
modprobe vfio_pci allow_wc_bar=1
modprobe mlx5_ib force_wc_vf=1

# Or via QEMU
qemu -device vfio-pci,host=03:00.0,...
     -enable-kvm -machine virt,gic-version=3
```

## Performance Impact

Measured with `ib_read_lat` on arm64 + SMMU + ConnectX-5:

| Configuration           | Latency |
|-------------------------|---------|
| Host (BF enabled)       | ~2.45 usec |
| Guest (VFIO, current)  | ~2.95 usec |
| Host (BF disabled)      | ~2.94 usec |
| Guest (with RFC patches)| ~2.45 usec (expected) |

## Files

```
00-cover-letter.txt           - Email cover letter (RFC 0/2)
01-vfio-pci-wc-bar.patch      - PATCH 1/2: VFIO changes
01-vfio-pci-wc-bar-email.txt  - Email template for PATCH 1/2
02-mlx5-wc-vf-enable.patch    - PATCH 2/2: mlx5 changes
02-mlx5-wc-vf-enable-email.txt - Email template for PATCH 2/2
```

## Sending to Mailing Lists

```bash
# Cover letter
git send-email \
  --to linux-rdma@vger.kernel.org \
  --cc kvm@vger.kernel.org \
  --cc linux-arm-kernel@lists.infradead.org \
  --cc alex.williamson@redhat.com \
  --cc leon@kernel.org \
  00-cover-letter.txt

# PATCH 1/2
git send-email \
  --to linux-rdma@vger.kernel.org \
  --cc kvm@vger.kernel.org \
  --cc alex.williamson@redhat.com \
  01-vfio-pci-wc-bar.patch

# PATCH 2/2
git send-email \
  --to linux-rdma@vger.kernel.org \
  --cc leon@kernel.org \
  02-mlx5-wc-vf-enable.patch
```

## Known Limitations

1. WC mapping is only safe for trusted/single-tenant environments
2. Requires platform-specific validation of ordering guarantees
3. arm64 SMMU WC support must be verified on target platform
4. Not suitable for general production use without further hardening

## Community Acceptance Assessment

### Likely Accepted Points
- WC disabled by default (opt-in only)
- Explicit "experimental/unsafe" labeling
- Module parameters for control
- Quantized performance data provided

### Likely Questions
1. "What about ordering guarantees?" → "For trusted environments only, validated by platform testing"
2. "Why not generic VFIO feature?" → "RFC starts mlx5-specific; generalization can follow"
3. "Does arm64 SMMU support WC MMIO?" → "Tested on our platform; further validation needed"

## Next Steps

1. Submit RFC to mailing lists for feedback
2. Address review comments
3. Consider proper VFIO device-specific WC flag mechanism
4. Add proper VF detection instead of module parameter
5. Platform-specific testing and validation
