#!/bin/bash
#========================================
# qcow2虚拟机启动脚本
#========================================
# SSH连接方式:
#   ssh root@192.168.90.141 -p 2222
# 
# 登录账号: root
# 登录密码: <PASSWORD>
#
# 或使用sshpass自动登录:
#   sshpass -p '<PASSWORD>' ssh -o StrictHostKeyChecking=no root@192.168.90.141 -p 2222
#
# 前台运行，Ctrl+C停止虚机
#========================================

qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4G \
  -kernel Image \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic