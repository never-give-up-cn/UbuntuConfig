# eD2k 下载配置记录

## 安装过程

```bash
# 安装 aMule
sudo apt-get update
sudo apt-get install -y amule-daemon amule-utils

# 生成配置文件（首次运行后自动生成）
amuled --ec-config
```

## 配置文件

- `~/.aMule/amule.conf` - 主配置文件
- `~/.aMule/remote.conf` - 远程连接配置

### 关键配置项

```ini
[ExternalConnect]
AcceptExternalConnections=1   # 开启外部连接
ECPort=4712                   # 控制端口
ECPassword=****               # 连接密码(MD5)

[General]
IncomingDir=/home/pi/Download  # 下载完成目录
TempDir=/home/pi/Download/temp # 临时目录
```

## 启动与管理

```bash
# 启动守护进程
amuled -f

# 查看状态
amulecmd -P "1" -c "Status"

# 查看下载列表
amulecmd -P "1" -c "show dl"

# 添加下载
amulecmd -P "1" -c "Add <ed2k_link>"

# 断开/连接网络
amulecmd -P "1" -c "Disconnect"
amulecmd -P "1" -c "Connect"
```

## 自启配置

通过 systemd 用户服务实现开机自启：

```bash
# ~/.config/systemd/user/amuled.service
systemctl --user enable amuled.service
systemctl --user restart amuled.service
```

## 当前下载任务

- **文件**: `zh-cn_windows_11_business_editions_version_25h2_updated_june_2026_arm64_dvd_669c2513.iso`
- **大小**: ~8.45 GB
- **Hash**: `46DC5D1A6C0DC244956C5B807011EC46`
- **链接**: `ed2k://|file|zh-cn_windows_11_business_editions_version_25h2_updated_june_2026_arm64_dvd_669c2513.iso|8452272128|46DC5D1A6C0DC244956C5B807011EC46|/`

## 网络状态

- eD2k: Connected (LowID)
- Kad: Connected (firewalled)
