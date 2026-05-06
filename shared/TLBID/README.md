```
/root/qemu/qemu/build/qemu-system-aarch64 -M virt -cpu cortex-a57 \
-smp 8 -m 2G -bios /usr/share/edk2/aarch64/QEMU_EFI.fd \
-kernel /root/openeuler/kernel/arch/arm64/boot/Image.gz  \
-initrd /boot/initramfs-6.6.0-132.0.0.111.oe2403sp3.aarch64.img \
-append "console=ttyAMA0 root=/dev/ram0 acpi=force" \
-tlbidomain domain_id=0,cpus=0-7 -tlbidomain domain_id=1,cpus=0-3 -tlbidomain domain_id=2,cpus=4-7 \
-accel tcg -nographic
```

./qemu-system-aarch64 -M virt -cpu cortex-a57 \
-smp 8 -m 2G -bios ./edk2-aarch64-code.fd \
-kernel ./Image.gz  \
-append "console=ttyAMA0 root=/dev/ram0 acpi=force" \
-tlbidomain domain_id=0,cpus=0-7 -tlbidomain domain_id=1,cpus=0-3 -tlbidomain domain_id=2,cpus=4-7 \
-accel tcg -nographic
