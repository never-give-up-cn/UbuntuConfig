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
