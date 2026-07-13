# PXE 无盘系统配置文档

## 架构概述

```
┌─────────────────────────────────────────────────────────┐
│                   PXE 服务器 (Ubuntu 26.04)              │
│                    192.168.183.131                       │
│                                                         │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌───────────┐  │
│  │ dnsmasq │  │   TFTP   │  │  NFS   │  │  iSCSI    │  │
│  │ DHCP    │  │  服务    │  │ 导出   │  │  Target   │  │
│  │ +Proxy  │  │ pxelinux │  │ pxeboot│  │ windows11 │  │
│  └─────────┘  └──────────┘  └────────┘  └───────────┘  │
│       │              │            │            │        │
│       └──────────────┴────────────┴────────────┘        │
│                        │                                │
│                  192.168.183.x                          │
│                        │                                │
└────────────────────────┴────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
   ┌──────▼──────┐              ┌──────▼──────┐
   │  BIOS 客户端 │              │ UEFI 客户端  │
   │ PXE → pxelinux.0           │ PXE → bootx64.efi
   └─────────────┘              └─────────────┘
```

## 服务组件

| 服务 | 端口 | 用途 |
|------|------|------|
| dnsmasq (DHCP) | UDP 67-68 | 分配 IP 地址 |
| dnsmasq (TFTP) | UDP 69 | 传输启动文件 |
| NFS | TCP 2049 | Linux 网络根文件系统 |
| Samba | TCP 445 | Windows 安装文件共享 |
| iSCSI | TCP 3260 | 无盘 Windows 启动 |

## 快速安装

在服务器上执行：

```bash
# 下载脚本
wget -q -O - https://raw.githubusercontent.com/never-give-up-cn/UbuntuConfig/main/setup-pxe.sh | bash

# 或者从本地运行
cd ~/UbuntuConfig
sudo bash setup-pxe.sh
```

## 客户端 PXE 启动

### 启动菜单选项

| 选项 | 功能 |
|------|------|
| 1. Boot from Local Disk | 从本地硬盘启动 |
| 2. Memory Test | 内存测试 |
| 3. Ubuntu Live (NFS) | Ubuntu Live 系统（需先准备） |
| 4. Windows PE (Network Boot) | Windows PE 维护环境 |
| 5. Windows 11 Setup | Windows 11 安装 |
| 6. iPXE Shell | iPXE 命令行 |
| 7. Shutdown | 关机 |
| 8. Reboot | 重启 |

## 准备 Windows PE 环境

### 方法1：使用 Windows ADK 创建 WinPE

在 Windows 机器上：

```batch
:: 安装 Windows ADK，选择 Windows PE 组件
:: 然后创建 WinPE ISO

copype amd64 C:\WinPE_amd64
MakeWinPEMedia /ISO C:\WinPE_amd64 C:\WinPE.iso
```

将 WinPE.iso 复制到服务器：

```bash
# 挂载 ISO 并解压到 WinPE 目录
mount -o loop /path/to/WinPE.iso /mnt
cp -r /mnt/* /srv/winpe/
```

### 方法2：等待 Windows 11 ISO 下载完成

当前下载路径：`/home/pi/Download/`

```bash
# ISO 下载完成后，挂载并提取安装文件
mkdir -p /srv/winpe/sources
mount -o loop /home/pi/Download/zh-cn_windows_11_*.iso /mnt
cp /mnt/sources/boot.wim /srv/winpe/
cp /mnt/sources/install.wim /srv/winpe/sources/
cp /mnt/bootmgr /srv/winpe/
cp /mnt/bootmgr.exe /srv/winpe/
umount /mnt
```

## iSCSI 无盘 Windows 11 配置

### 步骤1：在服务器上创建 iSCSI 目标

```bash
# 已在 setup-pxe.sh 中自动完成
# 查看 iSCSI 目标
tgtadm --mode target --op show
```

### 步骤2：在 Windows 客户端连接 iSCSI

1. 打开 **iSCSI 发起程序** (Control Panel → 管理工具)
2. 在目标框中输入：`192.168.183.131`
3. 点击 **快速连接**
4. 输入 CHAP 密钥：用户 `pxeuser`，密码 `P@ssw0rd`

### 步骤3：安装 Windows 到 iSCSI 磁盘

1. 从 Windows 11 安装介质启动
2. 在安装程序中按 `Shift+F10` 打开命令提示符
3. 连接 iSCSI：
   ```cmd
   net use y: \\192.168.183.131\Win11
   ```
4. 将 Windows 安装到 iSCSI 磁盘
5. 配置 iPXE 从 iSCSI 启动

### 步骤4：配置 iPXE 启动脚本

```ipxe
#!ipxe

set iqni iqn.2026-07.local.pxe:windows11
set username pxeuser
set password P@ssw0rd

sanboot iscsi:192.168.183.131::::iqn.2026-07.local.pxe:windows11
```

## 故障排除

### 客户端获取不到 IP

```bash
# 检查 dnsmasq 日志
tail -f /var/log/pxe/dnsmasq.log

# 检查 dnsmasq 状态
systemctl status dnsmasq

# 检查端口监听
ss -tuln | grep -E '67|68|69'
```

### PXE 启动文件找不到

```bash
# 检查 TFTP 目录
ls -la /srv/tftp/

# 测试 TFTP 连接
tftp 192.168.183.131 -c get pxelinux.0
```

### 客户端 PXE 引导后黑屏

- 检查客户端是 BIOS 还是 UEFI 模式
- BIOS 用 `pxelinux.0`
- UEFI 用 `efi/bootx64.efi`

### iSCSI 连接失败

```bash
# 检查 iSCSI 目标状态
tgtadm --mode target --op show

# 检查防火墙
ufw status | grep 3260
```

## 目录结构

```
/srv/
├── tftp/                        # TFTP 根目录
│   ├── pxelinux.0              # BIOS PXE 引导
│   ├── pxelinux.cfg/
│   │   └── default             # PXE 菜单配置
│   ├── efi/
│   │   └── bootx64.efi         # UEFI PXE 引导
│   ├── ldlinux.c32
│   ├── libutil.c32
│   ├── menu.c32
│   ├── vesamenu.c32
│   ├── wimboot                  # Windows PE 引导
│   ├── ipxe.pxe / ipxe.efi     # iPXE
│   └── undionly.kpxe           # 通用 PXE
├── nfs/
│   └── pxeboot/                # NFS 导出目录（Linux 网络启动）
├── winpe/                       # Windows PE / 安装文件
│   ├── bootmgr
│   ├── bootmgr.exe
│   ├── boot.wim
│   └── sources/
│       └── install.wim
└── iscsi/
    └── windows11.img            # iSCSI 磁盘映像 (64G)
```
