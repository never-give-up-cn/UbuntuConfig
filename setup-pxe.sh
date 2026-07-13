#!/bin/bash
# ============================================================
# PXE 无盘系统安装脚本
# Ubuntu 26.04 LTS + dnsmasq + NFS + iSCSI
# 支持 PXE 启动 Linux Live 和 Windows PE
# ============================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; }

# ===== 配置参数（按需修改）=====
PXE_IFACE="ens33"           # PXE 服务网卡
PXE_IP="192.168.183.131"    # 本机 IP
DHCP_RANGE_START="192.168.183.200"
DHCP_RANGE_END="192.168.183.250"
DHCP_NETMASK="255.255.255.0"
DHCP_GATEWAY="192.168.183.2"
DHCP_DNS="114.114.114.114"
TFTP_ROOT="/srv/tftp"
NFS_ROOT="/srv/nfs/pxeboot"
WINPE_DIR="/srv/winpe"

# ===== 确保以 root 运行 =====
if [ "$EUID" -ne 0 ]; then
    echo "请使用 sudo 运行此脚本"
    exec sudo "$0" "$@"
    exit 1
fi

echo "=============================================="
echo "    PXE 无盘系统安装脚本"
echo "    Ubuntu 26.04 LTS"
echo "=============================================="
echo ""

# ===== 第1步：安装必要软件包 =====
echo ""
echo "━━━ 第1步：安装 PXE 相关软件 ━━━"

apt-get update -qq
apt-get install -y \
    dnsmasq \
    nfs-kernel-server \
    syslinux \
    pxelinux \
    samba \
    tgt \
    wget \
    net-tools

log "软件包安装完成"

# ===== 第2步：创建目录结构 =====
echo ""
echo "━━━ 第2步：创建目录结构 ━━━"

mkdir -p $TFTP_ROOT/pxelinux.cfg
mkdir -p $TFTP_ROOT/efi
mkdir -p $NFS_ROOT
mkdir -p $WINPE_DIR
mkdir -p /var/log/pxe

log "目录结构创建完成"

# ===== 第3步：复制 PXE 启动文件 =====
echo ""
echo "━━━ 第3步：复制 PXE 启动文件 ━━━"

# BIOS PXE 文件
cp /usr/lib/syslinux/modules/bios/ldlinux.c32 $TFTP_ROOT/ 2>/dev/null || true
cp /usr/lib/syslinux/modules/bios/libutil.c32 $TFTP_ROOT/ 2>/dev/null || true
cp /usr/lib/syslinux/modules/bios/menu.c32 $TFTP_ROOT/ 2>/dev/null || true
cp /usr/lib/syslinux/modules/bios/vesamenu.c32 $TFTP_ROOT/ 2>/dev/null || true
cp /usr/lib/syslinux/modules/bios/pxelinux.0 $TFTP_ROOT/ 2>/dev/null || true

# 如果找不到文件，尝试其他位置
if [ ! -f $TFTP_ROOT/pxelinux.0 ]; then
    find /usr -name "pxelinux.0" -type f -exec cp {} $TFTP_ROOT/ \; 2>/dev/null || true
fi

# 下载 EFI PXE 文件（用于 UEFI 启动）
if [ ! -f $TFTP_ROOT/efi/bootx64.efi ]; then
    # 使用 grub-efi 或 ipxe.efi
    apt-get install -y grub-efi-amd64-bin 2>/dev/null || true
    if [ -f /usr/lib/grub/x86_64-efi/grubnetx64.efi ]; then
        cp /usr/lib/grub/x86_64-efi/grubnetx64.efi $TFTP_ROOT/efi/bootx64.efi
    fi
fi

# 下载 iPXE
if [ ! -f $TFTP_ROOT/ipxe.efi ]; then
    wget -q -O $TFTP_ROOT/ipxe.efi "http://boot.ipxe.org/ipxe.efi" 2>/dev/null || warn "iPXE EFI 下载失败"
    wget -q -O $TFTP_ROOT/ipxe.pxe "http://boot.ipxe.org/ipxe.pxe" 2>/dev/null || warn "iPXE PXE 下载失败"
fi

# 下载 undionly.kpxe（万能PXE）
if [ ! -f $TFTP_ROOT/undionly.kpxe ]; then
    wget -q -O $TFTP_ROOT/undionly.kpxe "http://boot.ipxe.org/undionly.kpxe" 2>/dev/null || warn "undionly.kpxe 下载失败"
fi

log "PXE 启动文件复制完成"

# ===== 第4步：配置 dnsmasq（DHCP + TFTP + Proxy DHCP）=====
echo ""
echo "━━━ 第4步：配置 dnsmasq ━━━"

cat > /etc/dnsmasq.d/pxe.conf << DNSMASQEOF
# ======================================================
# dnsmasq PXE 配置
# 提供 DHCP + TFTP + ProxyDHCP 服务
# ======================================================

# 监听的网络接口
interface=$PXE_IFACE
bind-dynamic

# ----- DHCP 服务 -----
# 启用 DHCP（如果网络已有 DHCP，注释掉以下两行，只保留 ProxyDHCP）
dhcp-range=$DHCP_RANGE_START,$DHCP_RANGE_END,12h
dhcp-option=3,$DHCP_GATEWAY
dhcp-option=6,$DHCP_DNS

# ----- TFTP 服务 -----
enable-tftp
tftp-root=$TFTP_ROOT
tftp-secure

# ----- PXE/BOOTP -----
# BIOS PXE 启动
dhcp-boot=pxelinux.0

# UEFI PXE 启动（根据客户端架构选择不同启动文件）
dhcp-match=set:efi-x64,option:client-arch,7
dhcp-match=set:efi-x64,option:client-arch,9
dhcp-match=set:efi-ia32,option:client-arch,6
dhcp-boot=tag:efi-x64,efi/bootx64.efi
dhcp-boot=tag:efi-ia32,efi/bootia32.efi

# iPXE 回退
dhcp-userclass=set:ipxe,iPXE
dhcp-boot=tag:ipxe,http://$PXE_IP/ipxe.php

# 日志
log-dhcp
log-facility=/var/log/pxe/dnsmasq.log
DNSMASQEOF

log "dnsmasq 配置完成"

# ===== 第5步：PXE 菜单配置 =====
echo ""
echo "━━━ 第5步：PXE 启动菜单 ━━━"

cat > $TFTP_ROOT/pxelinux.cfg/default << PXEMENU
UI vesamenu.c32
MENU TITLE PXE Boot Server - Ubuntu 26.04
MENU COLOR border 30;44 #ffffffff #00000000
MENU COLOR title 1;36;44 #ffffffff #00000000
MENU COLOR sel 7;37;44 #ffffffff #ee000000
MENU COLOR unsel 37;44 #ffffffff #00000000
MENU COLOR help 34;44 #ffffffff #00000000
MENU COLOR timeout_msg 36;44 #ffffffff #00000000
TIMEOUT 300
DEFAULT vesamenu.c32

LABEL local
    MENU LABEL ^1. Boot from Local Disk
    LOCALBOOT 0

LABEL memtest
    MENU LABEL ^2. Memory Test
    KERNEL memtest86+

LABEL ubuntu-live
    MENU LABEL ^3. Ubuntu Live (NFS)
    KERNEL vmlinuz
    APPEND initrd=initrd.img root=/dev/nfs nfsroot=$PXE_IP:$NFS_ROOT ip=dhcp rw

LABEL winpe
    MENU LABEL ^4. Windows PE (Network Boot)
    KERNEL wimboot
    APPEND initrd=@bootmgr=/srv/winpe/bootmgr
            initrd=@bootmgr.exe=/srv/winpe/bootmgr.exe
            initrd=@bcd=/srv/winpe/bcd
            initrd=@boot.sdi=/srv/winpe/boot.sdi
            initrd=@boot.wim=/srv/winpe/winpe.wim

LABEL windows-setup
    MENU LABEL ^5. Windows 11 Setup (via Samba)
    KERNEL wimboot
    APPEND initrd=@bootmgr=/srv/winpe/bootmgr
            initrd=@bootmgr.exe=/srv/winpe/bootmgr.exe
            initrd=@bcd=/srv/winpe/bcd
            initrd=@boot.sdi=/srv/winpe/boot.sdi
            initrd=@boot.wim=/srv/winpe/windows11-install.wim

LABEL ipxe-shell
    MENU LABEL ^6. iPXE Shell
    KERNEL ipxe.pxe

LABEL shutdown
    MENU LABEL ^7. Shutdown
    COM32 poweroff.c32

LABEL reboot
    MENU LABEL ^8. Reboot
    COM32 reboot.c32
PXEMENU

# 下载 wimboot（Windows PE 启动需要）
if [ ! -f $TFTP_ROOT/wimboot ]; then
    wget -q -O /tmp/wimboot.zip "https://github.com/ipxe/wimboot/releases/latest/download/wimboot" 2>/dev/null && \
        cp /tmp/wimboot $TFTP_ROOT/wimboot && chmod 644 $TFTP_ROOT/wimboot || \
        warn "wimboot 下载失败, 稍后需要手动下载"
fi

log "PXE 启动菜单配置完成"

# ===== 第6步：配置 NFS（Linux 网络启动）=====
echo ""
echo "━━━ 第6步：配置 NFS ━━━"

echo "$NFS_ROOT *(ro,no_subtree_check,fsid=0)" >> /etc/exports
exportfs -r

log "NFS 配置完成"

# ===== 第7步：配置 Samba（Windows 安装文件共享）=====
echo ""
echo "━━━ 第7步：配置 Samba ━━━"

cat > /etc/samba/smb.conf << SAMBAEOF
[global]
   workgroup = WORKGROUP
   server string = PXE Server
   netbios name = PXE-SERVER
   security = user
   map to guest = Bad User
   guest account = nobody

[Win11]
   path = $WINPE_DIR
   browseable = yes
   read only = yes
   guest ok = yes
   public = yes

[ISO]
   path = /home/pi/Download
   browseable = yes
   read only = yes
   guest ok = yes
SAMBAEOF

log "Samba 配置完成"

# ===== 第8步：配置 iSCSI Target（无盘 Windows 需要）=====
echo ""
echo "━━━ 第8步：配置 iSCSI Target ━━━"

cat > /etc/tgt/conf.d/pxe-target.conf << TGTEOF
# iSCSI Target 配置
# 用于无盘 Windows 启动
# 备注：需要先用 Windows 安装到 iSCSI 磁盘，才能用于 PXE 启动

<target iqn.2026-07.local.pxe:windows11>
    backing-store /srv/iscsi/windows11.img
    initiator-address 192.168.183.0/24
    incominguser pxeuser P@ssw0rd
</target>
TGTEOF

# 创建 iSCSI 磁盘文件（需要 Windows ISO 下载完成后才初始化）
mkdir -p /srv/iscsi
# 创建一个 64G 的稀疏文件（不立即占用空间）
truncate -s 64G /srv/iscsi/windows11.img
log "iSCSI Target 配置完成（磁盘文件已创建，64G 稀疏文件）"

# ===== 第9步：配置防火墙 =====
echo ""
echo "━━━ 第9步：配置防火墙 ━━━"

# TFTP (UDP 69)
ufw allow 69/udp comment 'TFTP'
# DHCP (UDP 67-68)
ufw allow 67:68/udp comment 'DHCP'
# NFS (TCP 2049)
ufw allow 2049 comment 'NFS'
# Samba (TCP 445, 139)
ufw allow 445 comment 'Samba'
ufw allow 139 comment 'Samba NetBIOS'
# iSCSI (TCP 3260)
ufw allow 3260 comment 'iSCSI'
# HTTP (用于 iPXE)
ufw allow 80/tcp comment 'HTTP'

log "防火墙规则已添加"

# ===== 第10步：启用并启动服务 =====
echo ""
echo "━━━ 第10步：启动服务 ━━━"

# 停止可能冲突的 systemd-resolved
systemctl stop systemd-resolved 2>/dev/null || true

# 先停止已有服务
systemctl stop dnsmasq 2>/dev/null || true
systemctl stop nfs-kernel-server 2>/dev/null || true
systemctl stop smbd 2>/dev/null || true
systemctl stop tgtd 2>/dev/null || true

sleep 2

# 重启服务
systemctl restart dnsmasq
systemctl restart nfs-kernel-server
systemctl restart smbd
systemctl restart tgtd

# 启用开机自启
systemctl enable dnsmasq
systemctl enable nfs-kernel-server
systemctl enable smbd
systemctl enable tgtd

log "所有服务已启动并启用开机自启"

# ===== 完成 =====
echo ""
echo "=============================================="
echo -e "${GREEN}  PXE 无盘系统配置完成！${NC}"
echo "=============================================="
echo ""
echo "服务状态:"
systemctl status dnsmasq --no-pager -l | head -3
systemctl status nfs-kernel-server --no-pager -l | head -3
systemctl status smbd --no-pager -l | head -3
systemctl status tgtd --no-pager -l | head -3
echo ""
echo "TFTP 目录: $TFTP_ROOT"
echo "NFS 目录: $NFS_ROOT"
echo "WinPE 目录: $WINPE_DIR"
echo "iSCSI 磁盘: /srv/iscsi/windows11.img (64G)"
echo ""
echo "Windows 11 无盘启动后续步骤:"
echo "  1. 等待 Windows 11 ISO 下载完成"
echo "  2. 解压 ISO 到 $WINPE_DIR/sources/"
echo "  3. 在另一台 Windows 机器上连接到 iSCSI 目标"
echo "  4. 将 Windows 11 安装到 iSCSI 磁盘"
echo "  5. 配置 iPXE 从 iSCSI 启动"
echo ""
echo "DHCP 地址池: $DHCP_RANGE_START - $DHCP_RANGE_END"
echo "客户端将自动获取 IP 并通过 PXE 启动"
echo ""
