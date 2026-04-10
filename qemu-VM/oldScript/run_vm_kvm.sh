qemu-system-aarch64 \
  -machine virt,virtualization=true -cpu max \
  -smp 8 \
  -m 6G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler-24.03-LTS-aarch64.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -virtfs local,path=../kernel,mount_tag=host-kernel,security_model=mapped \
  -nographic \
  -rtc clock=host,base=localtime


#qemu-system-aarch64 \
#  -machine virt,accel=hvf -cpu max \
#  -smp 8 \
#  -m 6G \
#  -bios edk2-aarch64-code.fd \
#  -drive file=openEuler-24.03-LTS-aarch64.qcow2,if=none,id=hd0,format=qcow2 \
#  -device virtio-blk-pci,drive=hd0 \
#  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
#  -device virtio-net-pci,netdev=net0 \
#  -virtfs local,path=../kernel,mount_tag=host-kernel,security_model=mapped \
#  -nographic \
#  -rtc clock=host,base=localtime
