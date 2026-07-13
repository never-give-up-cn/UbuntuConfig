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

详见 [docs/pxe-diskless-setup.md](docs/pxe-diskless-setup.md)

| 服务 | 用途 | 状态 |
|------|------|------|
| dnsmasq (DHCP+TFTP) | IP 分配 + PXE 文件传输 | ✅ active |
| NFS | Linux 网络启动 | ✅ active |
| Samba | Windows 文件共享 | ✅ active |
| iSCSI | 无盘 Windows 启动 | ✅ active |

```bash
# 一键安装 PXE 服务
sudo bash setup-pxe.sh
```

## 系统架构

```
客户端 PXE → DHCP(获取IP) → TFTP(下载启动文件) 
         → PXE菜单 → 选择启动项
         ├─ 1. 本地启动
         ├─ 3. Ubuntu Live (NFS)
         ├─ 4. Windows PE (Samba)
         ├─ 5. Windows 11 安装
         └─ 6. iPXE Shell → iSCSI 无盘Windows
```
