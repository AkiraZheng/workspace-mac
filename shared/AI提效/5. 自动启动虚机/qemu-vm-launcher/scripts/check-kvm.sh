#!/bin/bash
# check-kvm.sh - 环境检查脚本（openEuler专属）
# 输出JSON格式报告

check_kvm() {
    if [ -e /dev/kvm ] && [ -w /dev/kvm ]; then
        echo "true"
    else
        echo "false"
    fi
}

check_hugepages() {
    local hp_2m=0
    local hp_1g=0
    
    if [ -f /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages ]; then
        hp_2m=$(cat /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages)
    fi
    
    if [ -f /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages ]; then
        hp_1g=$(cat /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages)
    fi
    
    echo "{\"2m\": $hp_2m, \"1g\": $hp_1g}"
}

check_transparent_hugepage() {
    if [ -f /sys/kernel/mm/transparent_hugepage/enabled ]; then
        cat /sys/kernel/mm/transparent_hugepage/enabled | grep -o '\[.*\]' | tr -d '[]'
    else
        echo "unknown"
    fi
}

check_vfio() {
    if lsmod | grep -q vfio_pci; then
        echo "true"
    else
        echo "false"
    fi
}

check_qemu() {
    if command -v qemu-system-aarch64 &> /dev/null; then
        local version=$(qemu-system-aarch64 --version | head -1)
        local is_kunpeng="false"
        if echo "$version" | grep -qi "kunpeng\|ubios"; then
            is_kunpeng="true"
        fi
        echo "{\"installed\": true, \"version\": \"$version\", \"is_kunpeng\": $is_kunpeng}"
    else
        echo "{\"installed\": false, \"version\": \"\", \"is_kunpeng\": false}"
    fi
}

check_edk2() {
    if rpm -qa | grep -q edk2-aarch64; then
        local firmware=""
        if [ -f /usr/share/edk2/aarch64/QEMU_EFI.fd ]; then
            firmware="/usr/share/edk2/aarch64/QEMU_EFI.fd"
        elif [ -f /usr/share/edk2/aarch64/QEMU_EFI-pflash.raw ]; then
            firmware="/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw"
        fi
        echo "{\"installed\": true, \"firmware\": \"$firmware\"}"
    else
        echo "{\"installed\": false, \"firmware\": \"\"}"
    fi
}

check_nbd() {
    if modprobe nbd max_part=8 2>/dev/null && [ -e /dev/nbd0 ]; then
        echo "true"
    else
        echo "false"
    fi
}

check_sshpass() {
    if command -v sshpass &> /dev/null; then
        echo "true"
    else
        echo "false"
    fi
}

check_xorriso() {
    if command -v xorriso &> /dev/null; then
        echo "true"
    else
        echo "false"
    fi
}

check_system() {
    local os=$(cat /etc/os-release | grep "^ID=" | cut -d= -f2 | tr -d '"')
    local arch=$(uname -m)
    echo "{\"os\": \"$os\", \"arch\": \"$arch\"}"
}

echo "{"
echo "  \"system\": $(check_system),"
echo "  \"kvm\": $(check_kvm),"
echo "  \"hugepages\": $(check_hugepages),"
echo "  \"transparent_hugepage\": \"$(check_transparent_hugepage)\","
echo "  \"vfio_pci_loaded\": $(check_vfio),"
echo "  \"qemu\": $(check_qemu),"
echo "  \"edk2\": $(check_edk2),"
echo "  \"nbd_available\": $(check_nbd),"
echo "  \"sshpass_installed\": $(check_sshpass),"
echo "  \"xorriso_installed\": $(check_xorriso)"
echo "}"