# UbuntuConfig

Ubuntu 26.04 LTS 服务器配置与使用记录

## 系统信息

- **主机名**: pi
- **IP**: 192.168.183.131
- **系统**: Ubuntu 26.04 LTS (Resolute Raccoon)
- **内核**: Linux 7.0.0-27-generic x86_64

## 目录结构

```
UbuntuConfig/
├── README.md              # 本文件
├── docs/
│   ├── ssh-connection.md  # SSH 连接记录
│   └── ed2k-download.md   # eD2k 下载配置
├── configs/
│   ├── amule.conf         # aMule 配置文件
│   └── remote.conf        # aMule 远程控制配置
├── setup.sh               # 一键安装脚本
└── 记录/
    └── 如何连接进来的.md  # 连接操作记录
```

## 已安装软件

| 软件 | 版本 | 用途 |
|------|------|------|
| aMule Daemon | 2.3.3 | eD2k/Kad 网络下载 |
| aMule Utils | 2.3.3 | aMule 命令行管理 |

## 快速使用

```bash
# SSH 连接
ssh pi@192.168.183.131

# 查看下载状态
amulecmd -P "1" -c "Status"
amulecmd -P "1" -c "show dl"
```


## PXE 无盘启动

| 服务 | 端口 | 状态 |
|------|------|------|
| dnsmasq (DHCP+TFTP) | UDP 67-69 | ✅ active |
| NFS | TCP 2049 | ✅ active |
| Samba | TCP 445 | ✅ active |
| iSCSI (tgt) | TCP 3260 | ✅ active |
| 监控面板 | TCP 8080 | ✅ active |

### PXE 启动选项

| # | 选项 | 适用架构 |
|---|------|---------|
| 1 | 本地启动 | 所有 |
| 2 | Ubuntu Live (NFS) | BIOS/UEFI |
| 3 | Windows PE (wimboot) | x86/x64 BIOS |
| 4 | Windows 11 安装 | ARM64 UEFI |
| 5 | iPXE Shell | 所有 |
| 6 | 内存测试 | 所有 |

### Windows 11 ARM64 启动文件

```
/home/pi/Download/zh-cn_windows_11_business_editions_version_25h2_updated_june_2026_arm64_dvd_669c2513.iso
  └── /srv/winpe/boot.wim    (684M)
  └── /srv/winpe/install.wim (7.0G)
  └── /srv/winpe/boot.sdi    (3.1M)
```

### TFTP 启动文件 (`/srv/tftp/`)

| 文件 | 用途 |
|------|------|
| pxelinux.0 | BIOS PXE 引导 |
| wimboot | Windows PE 引导 (BIOS/x64) |
| boot.wim | Windows PE 镜像 |
| boot.sdi | 启动 RAMDISK |
| efi/bootaa64.efi | ARM64 UEFI 网络启动 |

### 客户端 PXE 启动流程

```
BIOS/x64 客户端:
  PXE → DHCP(获取IP) → TFTP(pxelinux.0) → 启动菜单 → wimboot → Windows PE

ARM64 UEFI 客户端:
  PXE → DHCP(获取IP) → TFTP(bootaa64.efi) → Windows 启动管理器
```
