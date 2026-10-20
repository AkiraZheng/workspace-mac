#!/bin/bash
#========================================
# 从本地连接远程虚机
#========================================
# 远程主机: 192.168.90.141
# 远程虚机SSH端口: 2222
#
# 使用方法（在本地执行）:
#   ./connect-vm.sh
#
# 登录账号: root
# 登录密码: 通过环境变量 VM_PASSWORD 传入（export VM_PASSWORD=<PASSWORD>）
#========================================

# 清理known_hosts避免host key变化错误
ssh-keygen -R "[192.168.90.141]:2222" 2>/dev/null || true

# SSH连接
sshpass -p "${VM_PASSWORD:?请先 export VM_PASSWORD=<PASSWORD>}" ssh -o StrictHostKeyChecking=no \
  root@192.168.90.141 -p 2222