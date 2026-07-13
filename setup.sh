#!/bin/bash
# Ubuntu 服务器一键配置脚本
# Ubuntu 26.04 LTS

set -e

echo "=== 更新软件源 ==="
sudo apt-get update -qq

echo "=== 安装 aMule ==="
sudo apt-get install -y amule-daemon amule-utils

echo "=== 配置 aMule ==="
# 配置已在单独文件中，可按需复制
echo "请参考 configs/ 目录下的配置文件手动复制到 ~/.aMule/"

echo "=== 完成 ==="
echo "运行 amuled -f 启动守护进程"
echo "运行 amulecmd -P "密码" -c "Status" 查看状态"
