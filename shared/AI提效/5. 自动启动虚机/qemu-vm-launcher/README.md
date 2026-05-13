# QEMU VM Launcher Skill 使用说明

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
   ./scripts/download-image.sh -o . -v 24.03-LTS
   ```

3. **内核提取**（鲲鹏定制QEMU必须）
   ```bash
   ./scripts/extract-kernel.sh -i openEuler.qcow2
   ```

4. **SSH配置修复**（必须）
   ```bash
   ./scripts/fix-ssh-config.sh -i openEuler.qcow2
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

### 示例1：基础启动

**用户输入**：
> 帮我启动一个QEMU虚拟机，4核4G内存

**AI响应**：
1. 检查环境（调用check-kvm.sh）
2. 检查镜像文件
3. 修复SSH配置
4. 生成QEMU启动命令
5. 自测验证
6. 提供SSH登录信息

### 示例2：NUMA拓扑

**用户输入**：
> 启动一个8核8G的虚机，配置2节点NUMA拓扑

**AI响应**：
1. 生成NUMA配置参数
2. 提供完整启动命令

### 示例3：VFIO直通

**用户输入**：
> 我要直通一个PCI设备，BDF是0000:04:00.0

**AI响应**：
1. 提示VFIO准备工作
2. 生成VFIO直通命令

---

## 文件结构

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

### 1. 安装依赖

```bash
./scripts/install-deps.sh
```

### 2. 环境检查

```bash
./scripts/check-kvm.sh
```

### 3. 下载镜像

```bash
./scripts/download-image.sh -o . -v 24.03-LTS
```

### 4. 提取内核（鲲鹏定制QEMU必须）

```bash
./scripts/extract-kernel.sh -i openEuler.qcow2
```

### 5. 修复SSH配置（必须）

```bash
./scripts/fix-ssh-config.sh -i openEuler.qcow2
```

### 6. 启动虚拟机

```bash
./examples/start-basic.sh
```

### 7. SSH登录

```bash
# 等待60秒让虚拟机完全启动
sleep 60

# SSH登录
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
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
│   ├── direct-kernel.yaml # 直接内核启动模板
│   ├── numa.yaml         # NUMA拓扑模板
│   ├── vfio.yaml         # VFIO直通模板
│   ├── migration.yaml    # 热迁移模板
│   └── virtio.yaml       # VIRTIO设备模板
├── scripts/
│   ├── check-kvm.sh      # 环境检查脚本
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
./scripts/install-deps.sh
```

自动安装：
- qemu-system-aarch64
- edk2-aarch64（UEFI固件）
- xorriso（ISO创建）
- sshpass（SSH测试）
- openssl（密码hash）

### check-kvm.sh - 环境检查

```bash
./scripts/check-kvm.sh
```

输出JSON格式环境报告，包含：
- 系统信息（OS、架构）
- KVM可用性
- QEMU版本及是否鲲鹏定制版
- edk2固件状态
- nbd/sshpass/xorriso工具状态

### download-image.sh - 下载openEuler镜像

```bash
./scripts/download-image.sh -o ./images -v 24.03-LTS
```

参数：
- `-o`: 输出目录
- `-v`: 版本号

### extract-kernel.sh - 提取内核

```bash
./scripts/extract-kernel.sh -i openEuler.qcow2
```

参数：
- `-i`: 镜像文件
- `-o`: 输出目录（可选）

从镜像中提取vmlinuz和initramfs，用于直接内核启动。

### fix-ssh-config.sh - 修复SSH密码认证

**重要**: openEuler云镜像默认禁用SSH密码登录，必须运行此脚本修复。

```bash
./scripts/fix-ssh-config.sh -i openEuler.qcow2
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
./scripts/build-minifs.sh -o ./minifs.img -s 200M
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
./scripts/pin-cpu-1v1.sh <pid> 0,2,4,6
```

### pin-cpu-range.sh - 范围绑核

```bash
./scripts/pin-cpu-range.sh <pid> 0-3
```

输出JSON格式环境报告。

### download-image.sh - 下载openEuler镜像

```bash
./scripts/download-image.sh -o ./images -v 24.03-LTS
```

参数：
- `-o`: 输出目录
- `-v`: 版本号

### build-minifs.sh - 构建minifs

```bash
./scripts/build-minifs.sh -o ./minifs.img -s 200M
```

参数：
- `-o`: 输出路径
- `-s`: 镜像大小
- `--with-dev-tools`: 包含开发工具

### extract-kernel.sh - 提取内核

```bash
./scripts/extract-kernel.sh -i openEuler.qcow2
```

参数：
- `-i`: 镜像文件
- `-o`: 输出目录（可选）

### fix-ssh-config.sh - 修复SSH密码认证

**重要**: openEuler云镜像默认禁用SSH密码登录，需要运行此脚本修复。

```bash
./scripts/fix-ssh-config.sh -i openEuler.qcow2
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
./scripts/pin-cpu-1v1.sh <pid> 0,2,4,6
```

### pin-cpu-range.sh - 范围绑核

```bash
./scripts/pin-cpu-range.sh <pid> 0-3
```

---

## 手动启动示例

**重要**: 启动前必须先修复SSH配置！

```bash
# 修复SSH
./scripts/fix-ssh-config.sh -i openEuler.qcow2

# 提取内核（鲲鹏定制QEMU）
./scripts/extract-kernel.sh -i openEuler.qcow2

# 直接启动示例脚本
cd qemu-vm-launcher
./examples/start-basic.sh

# 或后台启动
nohup ./examples/start-basic.sh > vm.log 2>&1 &

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
./scripts/fix-ssh-config.sh -i openEuler.qcow2
```

### Q: 密码登录被拒绝？

openEuler云镜像默认禁用SSH密码认证，需要修复：

```bash
# 启用密码认证并设置root密码
./scripts/fix-ssh-config.sh -i openEuler.qcow2 -p {VM_PASSWORD}

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
- SSH密码认证：运行 `./scripts/fix-ssh-config.sh`
- 鲲鹏定制QEMU：使用直接内核启动（`-kernel vmlinuz -initrd initramfs.img`）
- 固件问题：安装 `edk2-aarch64` 包

**依赖包安装**：
```bash
./scripts/install-deps.sh
```
