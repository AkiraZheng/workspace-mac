#!/bin/bash
#========================================
# qcow2虚拟机启动脚本
#========================================
# 内核: /home/zt/vm-bootkit/vmlinuz + initramfs.img (提取自镜像)
# 镜像: /home/zt/vm-bootkit/openEuler-24.03-LTS-aarch64.qcow2
# 模式: KVM加速 / 4核(host) / 4G内存
#
# SSH连接方式:
#   ssh root@localhost -p 2222
#
# 登录账号: root
# 登录密码: VM_PASSWORD
#
# 或使用sshpass自动登录:
#   sshpass -p "VM_PASSWORD" ssh -o StrictHostKeyChecking=no root@localhost -p 2222
#
# 串口日志(后台启动时): /home/zt/vm-console.log
#========================================

qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4G \
  -kernel /home/zt/vm-bootkit/vmlinuz \
  -initrd /home/zt/vm-bootkit/initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=/home/zt/vm-bootkit/openEuler-24.03-LTS-aarch64.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
