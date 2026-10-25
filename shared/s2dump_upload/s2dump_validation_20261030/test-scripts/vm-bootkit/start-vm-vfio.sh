#!/bin/bash
#========================================
# qcow2虚拟机启动脚本（VFIO直通ZIP加速器）
#========================================
# 直通设备: 0000:31:00.0 HiSilicon ZIP Engine (IOMMU group 25)
# 宿主机保留: 0000:33:00.0 (ZIP Engine 1)
#
# 本脚本自动完成:
#   1. 解绑宿主机 hisi_zip 驱动
#   2. 绑定 vfio-pci
#   3. 启动QEMU虚机
#
# 启动后在虚机内加载加速器驱动:
#   modprobe hisi_zip
#   ls /sys/class/uacce/ && ls /dev/ | grep -iE "zip|uacce"
#
# 虚机关闭后宿主机恢复设备的方法:
#   echo 0000:31:00.0 > /sys/bus/pci/drivers/vfio-pci/unbind
#   echo "" > /sys/bus/pci/devices/0000:31:00.0/driver_override
#   echo 0000:31:00.0 > /sys/bus/pci/drivers/hisi_zip/bind
#
# SSH连接方式:
#   ssh root@localhost -p 2222
# 登录账号: root
# 登录密码: VM_PASSWORD
#
# 串口日志(后台启动时): /home/zt/vm-console.log
#========================================

BDF="0000:31:00.0"
DEV_PATH="/sys/bus/pci/devices/$BDF"

# 同一qcow2镜像不能被两个QEMU同时使用
if pgrep -x qemu-system-aar > /dev/null; then
    echo "错误: 已有QEMU虚机在运行"
    echo "请先停止: pkill -f qemu-system-aarch64"
    exit 1
fi

# 检查设备存在
if [ ! -e "$DEV_PATH" ]; then
    echo "错误: 设备 $BDF 不存在"
    exit 1
fi

modprobe vfio-pci

CURRENT_DRIVER=$(basename $(readlink $DEV_PATH/driver 2>/dev/null) 2>/dev/null)
if [ "$CURRENT_DRIVER" == "vfio-pci" ]; then
    echo "设备 $BDF 已绑定 vfio-pci，跳过绑定"
else
    echo "设置 driver_override..."
    echo vfio-pci > $DEV_PATH/driver_override
    if [ -n "$CURRENT_DRIVER" ]; then
        echo "解绑当前驱动 $CURRENT_DRIVER..."
        echo $BDF > /sys/bus/pci/drivers/$CURRENT_DRIVER/unbind
    fi
    echo "绑定 vfio-pci..."
    echo $BDF > /sys/bus/pci/drivers/vfio-pci/bind || {
        echo "错误: vfio-pci 绑定失败"
        exit 1
    }
fi

echo "=== 宿主机侧就绪，启动虚机（直通 $BDF ZIP加速器）==="

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
  -device vfio-pci,host=0000:31:00.0 \
  -nographic
