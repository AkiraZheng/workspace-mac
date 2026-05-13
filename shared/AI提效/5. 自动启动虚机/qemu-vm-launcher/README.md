# QEMU VM Launcher Skill 使用说明

## ⚠️ 重要：脚本定位方法

**执行任何脚本前必须先定位skill目录！**

所有文档中的脚本路径都是相对路径，实际执行时需要加上skill目录前缀：

```bash
# 定位skill目录
SKILL_DIR=$(find ~ -type d -name qemu-vm-launcher 2>/dev/null | head -1)

# 如果找不到，检查常见安装位置
for dir in ~/.config/opencode/skills ~/.claude/skills ~/.agents/skills; do
    if [ -d "$dir/qemu-vm-launcher" ]; then
        SKILL_DIR="$dir/qemu-vm-launcher"
        break
    fi
done

# 验证
echo "Skill目录: $SKILL_DIR"
ls "$SKILL_DIR/scripts/"

# 执行脚本示例（必须加前缀）
$SKILL_DIR/scripts/check-kvm.sh
$SKILL_DIR/scripts/download-image.sh -o . -v 24.03-LTS
$SKILL_DIR/scripts/ssh-test.sh
```

---

## 简介

本skill帮助用户快速启动QEMU aarch64虚拟机，提供：

**适用系统**: openEuler (aarch64)

- 镜像准备（openEuler qcow2下载或minifs构建）
- 分层配置向导
- QEMU命令自动生成
- SSH密码认证修复
- 完整脚本工具集

**注意**: 本skill仅支持openEuler系统，所有包管理命令使用yum。

---

## 安装方法

### 方法一：安装到用户配置目录（推荐）

```bash
# 复制skill到opencode用户配置目录
\cp -r qemu-vm-launcher ~/.config/opencode/skills/
```

### 方法二：安装到系统目录

```bash
# 复制skill到系统skills目录（需要root权限）
cp -r qemu-vm-launcher /root/.agents/skills/
```

### 方法三：在项目中使用（本地引用）

在项目目录创建 `AGENTS.md` 或 `CLAUDE.md`，添加：

```markdown
## Skills

使用本地skill：
- 路径: ./qemu-vm-launcher/SKILL.md
```

---

## 验证安装

安装后，重启opencode或Claude Code，skill会自动识别。

检查skill是否被识别：
- 在对话中提及 "启动QEMU虚拟机" 或 "openEuler镜像"
- AI应该会自动调用该skill

---

## 触发关键词

以下关键词会触发skill：

| 关键词 | 说明 |
|-------|------|
| 启动QEMU虚拟机 | 主要触发词 |
| 配置虚机 | 配置相关 |
| QEMU命令生成 | 命令生成 |
| openEuler镜像下载 | 镜像准备 |
| minifs构建 | 镜像构建 |
| NUMA拓扑 | 高级配置 |
| VFIO直通 | 设备直通 |
| 热迁移 | 迁移配置 |
| CPU绑核 | 性能优化 |

---

## 使用示例

### 完整启动流程

**用户输入**：
> 帮我启动一个QEMU虚拟机，4核4G内存

**AI完整执行流程**：

1. **环境检查**
   ```bash
   rpm -qa | grep qemu-system-aarch64
   rpm -qa | grep edk2-aarch64
   qemu-system-aarch64 -cpu help | grep Kunpeng
   ```

2. **镜像准备**
   ```bash
   # 下载openEuler镜像
   $SKILL_DIR/scripts/download-image.sh -o . -v 24.03-LTS
   ```

3. **内核提取**（鲲鹏定制QEMU必须）
   ```bash
   $SKILL_DIR/scripts/extract-kernel.sh -i openEuler.qcow2
   ```

4. **SSH配置修复**（必须）
   ```bash
   $SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
   ```

5. **自测验证**
   ```bash
   timeout 30 qemu-system-aarch64 -kernel vmlinuz -initrd initramfs.img ...
   # 确认能看到 systemd 启动日志
   ```

6. **生成启动脚本并执行**
   ```bash
   # 后台启动
   nohup ./start-vm.sh > vm.log 2>&1 &
   
   # 等待SSH就绪后测试
   sleep 60
   sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
   ```

### 示例1：基础启动（完整流程）

> ⚠️ **注意**：执行脚本前必须先定位skill目录！
> ```bash
> SKILL_DIR=$(find ~ -type d -name qemu-vm-launcher 2>/dev/null | head -1)
> ```

**用户输入**：
> 帮我启动一个QEMU虚拟机，4核4G内存

**AI完整执行流程**：

1. **环境检查**
   ```bash
   rpm -qa | grep qemu-system-aarch64
   rpm -qa | grep edk2-aarch64
   qemu-system-aarch64 -cpu help | grep Kunpeng
   ```

2. **镜像准备**
   ```bash
   # 下载openEuler镜像
   $SKILL_DIR/scripts/download-image.sh -o . -v 24.03-LTS
   ```

3. **内核提取**（鲲鹏定制QEMU必须）
   ```bash
   $SKILL_DIR/scripts/extract-kernel.sh -i openEuler.qcow2
   ```

4. **SSH配置修复**（必须）
   ```bash
   $SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
   ```
qemu-vm-launcher/
├── SKILL.md              # 主skill文件（必须有）
├── README.md             # 使用说明（本文件）
├── docs/
│   ├── qemu-commands.md  # QEMU命令说明书
│   ├── qemu-params.yaml  # 参数校验规则
│   └── qemu-reference.md # 参数参考文档
├── templates/
│   ├── basic.yaml        # 基础启动模板
│   ├── direct-kernel.yaml # 直接内核启动模板（鲲鹏定制QEMU）
│   ├── numa.yaml         # NUMA拓扑模板
│   ├── vfio.yaml         # VFIO直通模板
│   ├── migration.yaml    # 热迁移模板
│   └── virtio.yaml       # VIRTIO设备模板
├── scripts/
│   ├── install-deps.sh   # 安装依赖包（openEuler）
│   ├── check-kvm.sh      # 环境检查脚本
│   ├── check-port.sh     # 端口可用性检查脚本
│   ├── download-image.sh # 镜像下载脚本
│   ├── build-minifs.sh   # minifs构建脚本
│   ├── extract-kernel.sh # 内核提取脚本
│   ├── fix-ssh-config.sh # SSH密码认证修复脚本
│   ├── pin-cpu-1v1.sh    # 1v1绑核脚本
│   └── pin-cpu-range.sh  # 范围绑核脚本
└── examples/
    ├── start-basic.sh    # 启动示例（自动检测模式）
    └── start-direct-kernel.sh # 直接内核启动示例
```

---

## 快速开始

> ⚠️ **执行前必须定位skill目录！**
> ```bash
> # 定位skill目录
> SKILL_DIR=$(find ~ -type d -name qemu-vm-launcher 2>/dev/null | head -1)
> 
> # 若找不到，检查常见位置
> for dir in ~/.config/opencode/skills ~/.claude/skills ~/.agents/skills; do
>     [ -d "$dir/qemu-vm-launcher" ] && SKILL_DIR="$dir/qemu-vm-launcher" && break
> done
> 
> # 验证
> echo "Skill目录: $SKILL_DIR"
> ls "$SKILL_DIR/scripts/"
> ```

### 1. 安装依赖

```bash
$SKILL_DIR/scripts/install-deps.sh
```

### 2. 环境检查

```bash
$SKILL_DIR/scripts/check-kvm.sh
```

### 3. 端口检查

```bash
# 检查SSH端口是否可用，若占用自动寻找可用端口
$SKILL_DIR/scripts/check-port.sh -p 2222
# 输出: {"available_port": 2222, "original_port": 2222, "changed": false}
# 若端口2222被占用，自动返回下一个可用端口
```

参数说明：
- `-p`: 起始检查端口（默认2222）
- `-m`: 最大端口范围（默认65535）

### 4. 下载镜像

```bash
$SKILL_DIR/scripts/download-image.sh -o . -v 24.03-LTS
```

### 4. 提取内核（鲲鹏定制QEMU必须）

```bash
$SKILL_DIR/scripts/extract-kernel.sh -i openEuler.qcow2
```

### 5. 修复SSH配置（必须）

```bash
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
```

### 6. 启动虚拟机

```bash
$SKILL_DIR/examples/start-basic.sh
```

### 7. SSH连接测试

```bash
# 测试SSH连接（自动重试）
$SKILL_DIR/scripts/ssh-test.sh

# 或手动测试
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

### 8. SSH连接测试

```bash
# 使用ssh-test.sh自动测试（自动清理known_hosts）
$SKILL_DIR/scripts/ssh-test.sh
```

---

## SSH连接问题排查

### 问题：REMOTE HOST IDENTIFICATION HAS CHANGED

**原因**：之前连接过该端口但主机已更换（不同虚机使用同一端口）

**解决**：
```bash
# 方法1：使用ssh-test.sh（推荐，自动清理）
$SKILL_DIR/scripts/ssh-test.sh

# 方法2：手动清理
ssh-keygen -R "[localhost]:2222"
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

### 问题：Connection refused

**原因**：虚机未启动或sshd未运行

**排查**：
```bash
# 检查虚机是否运行
ps aux | grep qemu

# 检查端口是否监听
ss -tlnp | grep 2222
```

### 问题：Permission denied

**原因**：密码错误或SSH配置问题

**解决**：
```bash
# 修复SSH配置（需要重新挂载镜像）
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
```

---
qemu-vm-launcher/
├── SKILL.md              # 主skill文件（必须有）
├── README.md             # 使用说明（本文件）
├── docs/
│   ├── qemu-commands.md  # QEMU命令说明书
│   ├── qemu-params.yaml  # 参数校验规则
│   └── qemu-reference.md # 参数参考文档
├── templates/
│   ├── basic.yaml        # 基础启动模板
│   ├── direct-kernel.yaml # 直接内核启动模板
│   ├── numa.yaml         # NUMA拓扑模板
│   ├── vfio.yaml         # VFIO直通模板
│   ├── migration.yaml    # 热迁移模板
│   └── virtio.yaml       # VIRTIO设备模板
├── scripts/
│   ├── check-kvm.sh      # 环境检查脚本
│   ├── check-port.sh     # 端口可用性检查
│   ├── ssh-test.sh       # SSH连接测试
│   ├── ssh-config.sh     # SSH配置脚本
│   ├── download-image.sh # 镜像下载脚本
│   ├── build-minifs.sh   # minifs构建脚本
│   ├── extract-kernel.sh # 内核提取脚本
│   ├── pin-cpu-1v1.sh    # 1v1绑核脚本
│   └── pin-cpu-range.sh  # 范围绑核脚本
└── examples/
    ├── start-basic.sh    # 启动示例（自动检测模式）
    └── start-direct-kernel.sh # 直接内核启动示例
```

---

## 脚本使用

### install-deps.sh - 安装依赖包（openEuler）

```bash
$SKILL_DIR/scripts/install-deps.sh
```

自动安装：
- qemu-system-aarch64
- edk2-aarch64（UEFI固件）
- xorriso（ISO创建）
- sshpass（SSH测试）
- openssl（密码hash）

### check-kvm.sh - 环境检查

```bash
$SKILL_DIR/scripts/check-kvm.sh
```

输出JSON格式环境报告，包含：
- 系统信息（OS、架构）
- KVM可用性
- QEMU版本及是否鲲鹏定制版
- edk2固件状态
- nbd/sshpass/xorriso工具状态

### download-image.sh - 下载openEuler镜像

```bash
$SKILL_DIR/scripts/download-image.sh -o ./images -v 24.03-LTS
```

参数：
- `-o`: 输出目录
- `-v`: 版本号

### extract-kernel.sh - 提取内核

```bash
$SKILL_DIR/scripts/extract-kernel.sh -i openEuler.qcow2
```

参数：
- `-i`: 镜像文件
- `-o`: 输出目录（可选）

从镜像中提取vmlinuz和initramfs，用于直接内核启动。

### fix-ssh-config.sh - 修复SSH密码认证

**重要**: openEuler云镜像默认禁用SSH密码登录，必须运行此脚本修复。

```bash
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
```

参数：
- `-i`: 镜像文件
- `-p`: root密码（可选，默认{VM_PASSWORD}）

**功能**：
1. 生成SSH host keys（rsa/ecdsa/ed25519）
2. 删除cloud-init的密码禁用配置
3. 设置root密码

**注意**：运行此脚本后启动虚拟机即可SSH密码登录，无需cloud-init。

### build-minifs.sh - 构建minifs

```bash
$SKILL_DIR/scripts/build-minifs.sh -o ./minifs.img -s 200M
```

参数：
- `-o`: 输出路径
- `-s`: 镜像大小
- `--with-dev-tools`: 包含开发工具

### pin-cpu-1v1.sh - 1v1绑核

```bash
# 获取QEMU进程ID
ps aux | grep qemu

# 绑核
$SKILL_DIR/scripts/pin-cpu-1v1.sh <pid> 0,2,4,6
```

### pin-cpu-range.sh - 范围绑核

```bash
$SKILL_DIR/scripts/pin-cpu-range.sh <pid> 0-3
```

输出JSON格式环境报告。

### download-image.sh - 下载openEuler镜像

```bash
$SKILL_DIR/scripts/download-image.sh -o ./images -v 24.03-LTS
```

参数：
- `-o`: 输出目录
- `-v`: 版本号

### build-minifs.sh - 构建minifs

```bash
$SKILL_DIR/scripts/build-minifs.sh -o ./minifs.img -s 200M
```

参数：
- `-o`: 输出路径
- `-s`: 镜像大小
- `--with-dev-tools`: 包含开发工具

### extract-kernel.sh - 提取内核

```bash
$SKILL_DIR/scripts/extract-kernel.sh -i openEuler.qcow2
```

参数：
- `-i`: 镜像文件
- `-o`: 输出目录（可选）

### fix-ssh-config.sh - 修复SSH密码认证

**重要**: openEuler云镜像默认禁用SSH密码登录，需要运行此脚本修复。

```bash
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
```

参数：
- `-i`: 镜像文件
- `-p`: root密码（可选，默认{VM_PASSWORD}）

**功能**：
1. 生成SSH host keys
2. 删除cloud-init的密码禁用配置
3. 设置root密码

**注意**：运行此脚本后不需要cloud-init即可SSH登录。

### pin-cpu-1v1.sh - 1v1绑核

```bash
# 获取QEMU进程ID
ps aux | grep qemu

# 绑核
$SKILL_DIR/scripts/pin-cpu-1v1.sh <pid> 0,2,4,6
```

### pin-cpu-range.sh - 范围绑核

```bash
$SKILL_DIR/scripts/pin-cpu-range.sh <pid> 0-3
```

---

## 手动启动示例

**重要**: 启动前必须先修复SSH配置！

```bash
# 修复SSH
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2

# 提取内核（鲲鹏定制QEMU）
$SKILL_DIR/scripts/extract-kernel.sh -i openEuler.qcow2

# 直接启动示例脚本
cd qemu-vm-launcher
$SKILL_DIR/examples/start-basic.sh

# 或后台启动
nohup $SKILL_DIR/examples/start-basic.sh > vm.log 2>&1 &

# 等待启动完成（约60秒）
sleep 60

# SSH登录
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

---

## openEuler镜像信息

下载的openEuler镜像默认信息（修复后）：
- 用户名: `root`
- 密码: `{VM_PASSWORD}`（由fix-ssh-config.sh设置）
- SSH端口: `2222`（Host转发）

SSH登录：
```bash
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

**注意**: openEuler云镜像原始状态禁用SSH密码认证，必须使用fix-ssh-config.sh修复。

---

## 常见问题

### Q: skill没有被识别？

检查：
1. SKILL.md文件头部是否有正确的yaml metadata
2. skill目录是否放在正确位置
3. 重启opencode或Claude Code

### Q: 找不到UEFI固件？

```bash
# openEuler查找固件
find /usr/share -name "edk2-aarch64-code.fd" 2>/dev/null
find /usr/share/edk2 -name "*.fd" 2>/dev/null

# 安装固件包
yum install edk2-aarch64
```

### Q: 找不到SSH host keys？

openEuler云镜像默认SSH host keys为空文件，需要修复：

```bash
# 使用修复脚本
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
```

### Q: 密码登录被拒绝？

openEuler云镜像默认禁用SSH密码认证，需要修复：

```bash
# 启用密码认证并设置root密码
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2 -p {VM_PASSWORD}

# 测试SSH
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

### Q: KVM不可用？

检查：
```bash
ls -la /dev/kvm
```

若无权限：
```bash
chmod 666 /dev/kvm
```

或使用TCG模式（纯软件模拟）。

---

## 技术支持

如有问题，请查看：
- `docs/qemu-commands.md`: 详细命令说明
- `docs/qemu-reference.md`: 参数参考
- `templates/*.yaml`: 配置模板

**openEuler专属问题**：
- SSH密码认证：运行 `$SKILL_DIR/scripts/fix-ssh-config.sh`
- 鲲鹏定制QEMU：使用直接内核启动（`-kernel vmlinuz -initrd initramfs.img`）
- 固件问题：安装 `edk2-aarch64` 包

**依赖包安装**：
```bash
$SKILL_DIR/scripts/install-deps.sh
```
