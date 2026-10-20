#!/bin/bash
#========================================
# 远程虚拟机停止脚本（在远程主机执行）
#========================================

pkill -f qemu-system-aarch64
echo "虚机已停止"
sleep 1
ps aux | grep qemu-system-aarch64 | grep -v grep || echo "确认: 无QEMU进程运行"