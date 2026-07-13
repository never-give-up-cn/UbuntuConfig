#!/usr/bin/env python3
"""
PXE 服务器监控面板
监控服务状态和已连接的客户端
访问: http://192.168.183.131:8080
"""

import http.server
import json
import subprocess
import time
import os
import socket
import re
from datetime import datetime
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = 8080
REFRESH_SECONDS = 5  # 前端自动刷新间隔

# 环境设置
MY_ENV = os.environ.copy()
MY_ENV["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
MY_ENV["LANG"] = "C.UTF-8"

# ===== 监控命令定义 =====

def run(cmd, timeout=5):
    """执行 shell 命令，返回输出"""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, env=MY_ENV
        )
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""

def run_sudo(cmd, timeout=5):
    """使用 sudo 执行命令（无需密码）"""
    return run(f'sudo -n {cmd} 2>/dev/null', timeout)

def check_service(name):
    """检查 systemd 服务状态"""
    status = run(f"systemctl is-active {name} 2>/dev/null", 3)
    enabled = run(f"systemctl is-enabled {name} 2>/dev/null", 3)
    if not status:
        status = "inactive"
    if not enabled:
        enabled = "unknown"
    return {"name": name, "status": status, "enabled": enabled}

def get_dhcp_leases():
    """获取 DHCP 租约列表"""
    leases = []
    # dnsmasq leases file
    for path in ["/var/lib/misc/dnsmasq.leases", "/var/lib/dnsmasq/dnsmasq.leases"]:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        expiry_ts = int(parts[0])
                        mac = parts[1]
                        ip = parts[2]
                        hostname = parts[3] if parts[3] != "*" else ""
                        leases.append({
                            "expiry": datetime.fromtimestamp(expiry_ts).strftime("%H:%M:%S"),
                            "mac": mac,
                            "ip": ip,
                            "hostname": hostname,
                            "active": expiry_ts > time.time()
                        })
            break
    return leases

def get_samba_connections():
    """获取 Samba 连接信息"""
    connections = []
    out = run_sudo("smbstatus -L 2>/dev/null || true", 5)
    if out and len(out) > 10:
        for line in out.split("\n")[2:]:
            if line.strip():
                parts = line.split()
                if len(parts) >= 4:
                    connections.append({
                        "pid": parts[0] if parts[0].isdigit() else "",
                        "machine": parts[2] if len(parts) > 2 else "",
                        "ip": parts[3] if len(parts) > 3 else "",
                        "protocol": parts[4] if len(parts) > 4 else "",
                        "time": parts[6] if len(parts) > 6 else ""
                    })
    return connections

def get_iscsi_sessions():
    """获取 iSCSI 会话信息"""
    sessions = []
    out = run_sudo("tgtadm --mode target --op show 2>/dev/null || true", 5)
    if out and "Target" in out:
        for line in out.split("\n"):
            line = line.strip()
            if "Initiator" in line or "192.168" in line or "Connected" in line:
                sessions.append(line)
    return sessions

def get_nfs_clients():
    """获取 NFS 客户端"""
    clients = []
    out = run_sudo("showmount -a 2>/dev/null")
    if out:
        for line in out.strip().split("\n"):
            if line.strip() and "Hosts on" not in line:
                clients.append(line.strip())
    return clients

def get_pxe_log():
    """获取最近的 PXE/DHCP 日志"""
    logs = []
    for log_file in ["/var/log/pxe/dnsmasq.log", "/var/log/syslog", "/var/log/messages"]:
        if os.path.exists(log_file) and os.access(log_file, os.R_OK):
            try:
                with open(log_file) as f:
                    lines = f.readlines()
                    # Filter for PXE/DHCP related lines
                    for line in lines[-50:]:
                        if any(kw in line.lower() for kw in ["dhcp", "pxe", "tftp", "dnsmasq"]):
                            logs.append(line.strip())
                    if logs:
                        break
            except (IOError, PermissionError):
                continue
    # Also try journalctl for dnsmasq logs
    if not logs:
        out = run("journalctl -u dnsmasq --no-pager -n 10 2>/dev/null", 3)
        if out:
            logs = out.split("\n")[-10:]
    return logs[-30:]

def get_arp_table():
    """获取 ARP 表（发现网络上的主机）"""
    hosts = []
    out = run("ip neigh show 2>/dev/null", 3)
    if not out:
        out = run("arp -n 2>/dev/null", 3)
    if out:
        for line in out.split("\n"):
            line = line.strip()
            if not line or "incomplete" in line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                raw_state = parts[-1]
                state = raw_state if raw_state in ["REACHABLE", "STALE", "DELAY", "PERMANENT"] else "REACHABLE"
                hosts.append({
                    "ip": parts[0].replace("(", "").replace(")", ""),
                    "mac": parts[3] if parts[1] == "lladdr" else (parts[4] if len(parts) > 4 else parts[1]),
                    "state": state,
                })
    return hosts


def get_system_info():
    """获取系统信息"""
    uptime = run("uptime -p 2>/dev/null || uptime", 3)
    disk = run("df -h / | tail -1", 3)
    mem = run("free -h | grep Mem", 3)
    load = run("cat /proc/loadavg | cut -d' ' -f1-3", 3)
    return {"uptime": uptime or "N/A", "disk": disk or "N/A", "mem": mem or "N/A", "load": load or "N/A"}

def get_network_speed():
    """获取网络带宽速度和客户端连接详情"""
    iface = "ens33"
    def read_bytes():
        out = run(f"cat /proc/net/dev | grep {iface}", 2)
        if out:
            parts = out.split()
            if len(parts) >= 10:
                return int(parts[1]), int(parts[9])
        return 0, 0

    rx1, tx1 = read_bytes()
    time.sleep(1)
    rx2, tx2 = read_bytes()

    rx_speed = (rx2 - rx1) / 1024
    tx_speed = (tx2 - tx1) / 1024

    def fmt(kbps):
        if kbps > 1024:
            return f"{kbps/1024:.1f} MB/s"
        return f"{kbps:.1f} KB/s"

    # 获取各服务活跃连接
    services = {
        "TFTP (69)": run("ss -tunap 2>/dev/null | grep ':69 ' | grep -v '127.0.0.1' | wc -l", 2),
        "NFS (2049)": run("ss -tnap 2>/dev/null | grep ':2049 ' | wc -l", 2),
        "Samba (445)": run("ss -tnap 2>/dev/null | grep ':445 ' | ESTAB | wc -l", 2),
        "iSCSI (3260)": run("ss -tnap 2>/dev/null | grep ':3260 ' | wc -l", 2),
    }
    # 获取连接客户端IP列表
    client_ips = run("ss -tn 2>/dev/null | grep -E ':2049|:445|:3260' | awk '{print $5}' | cut -d: -f1 | sort -u", 3)

    return {
        "rx": fmt(rx_speed),
        "tx": fmt(tx_speed),
        "rx_raw": round(rx_speed, 1),
        "tx_raw": round(tx_speed, 1),
        "services": {k: int(v) if v.isdigit() else 0 for k, v in services.items()},
        "client_ips": client_ips.split("\n") if client_ips else []
    }

def get_iscsi_info():
    """获取 iSCSI 目标信息"""
    targets = []
    out = run_sudo("tgtadm --mode target --op show 2>/dev/null || true", 5)
    if out:
        current = {}
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("Target"):
                if current:
                    targets.append(current)
                current = {"name": line.split(":")[1].strip() if ":" in line else line, "luns": [], "acl": []}
            elif "LUN:" in line and "Type:" in line:
                pass
            elif "Backing store path:" in line:
                path = line.split(":")[1].strip()
                if path and path != "None":
                    current.setdefault("luns", []).append(path)
            elif "ACL information:" in line:
                pass
            elif current and current.get("name") and line and not any(x in line for x in ["System", "Driver", "State", "SCSI", "Size:", "Online:", "Type:", "Backing", "I_T nexus"]):
                if "192.168" in line or "iqn." in line:
                    current.setdefault("acl", []).append(line)
        if current:
            targets.append(current)
    return targets

def get_iso_mounts():
    """获取 ISO 挂载状态"""
    mounts = []
    out = run("mount | grep iso | grep -v sr0", 3)
    if out:
        for line in out.split("\n"):
            parts = line.split(" ")
            if len(parts) > 2:
                mounts.append({
                    "iso": parts[0] if parts[0].endswith(".iso") else "",
                    "mount": parts[2] if len(parts) > 2 else "",
                    "type": parts[-2] if len(parts) > 4 else ""
                })
    return mounts

def get_tftp_summary():
    """获取 TFTP 文件状态"""
    files = {}
    for f in ["pxelinux.0", "vesamenu.c32", "wimboot", "boot.sdi", "boot.wim", "ipxe.pxe", "undionly.kpxe"]:
        path = f"/srv/tftp/{f}"
        size = run(f"ls -lh {path} 2>/dev/null | awk '{{print $5}}'", 2)
        files[f] = size or "missing"
    return files

def get_pxe_menu_options():
    """获取 PXE 菜单选项"""
    options = []
    out = run("grep 'MENU LABEL' /srv/tftp/pxelinux.cfg/default 2>/dev/null", 3)
    if out:
        for line in out.split("\n"):
            if "^" in line:
                key = line.split("^")[1][0] if len(line.split("^")) > 1 else "?"
                label = line.split("LABEL")[-1].strip().split("^")[-1].strip() if "LABEL" in line else line.strip()
                options.append({"key": key, "label": label})
    return options

def get_nfs_clients_info():
    """获取 NFS 客户端信息"""
    clients = []
    out = run_sudo("showmount -a 2>/dev/null", 5)
    if out:
        for line in out.split("\n"):
            line = line.strip()
            if line and "All mount points" not in line:
                clients.append(line)
    return clients

# ===== HTML 模板 =====

HTML_HEADER = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="REFRESH_SECONDS">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PXE 服务器监控面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #0f1923;
            color: #e0e0e0;
            padding: 20px;
        }
        .header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 25px; padding-bottom: 15px;
            border-bottom: 1px solid #1e3a4f;
        }
        .header h1 {
            font-size: 24px; color: #4fc3f7;
            display: flex; align-items: center; gap: 10px;
        }
        .header h1 small { font-size: 14px; color: #78909c; font-weight: normal; }
        .header .time { color: #78909c; font-size: 13px; }
        .grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px; margin-bottom: 20px;
        }
        .card {
            background: #1a2a3a; border-radius: 10px; padding: 18px;
            border: 1px solid #263b4a; transition: all 0.3s;
        }
        .card:hover { border-color: #4fc3f7; box-shadow: 0 0 15px rgba(79,195,247,0.1); }
        .card-title {
            font-size: 12px; text-transform: uppercase; letter-spacing: 1px;
            color: #78909c; margin-bottom: 12px; display: flex; justify-content: space-between;
        }
        .service-status {
            display: flex; align-items: center; gap: 10px; padding: 6px 0;
        }
        .status-dot {
            width: 10px; height: 10px; border-radius: 50%; display: inline-block;
        }
        .status-dot.active { background: #4caf50; box-shadow: 0 0 8px #4caf50; }
        .status-dot.inactive { background: #f44336; box-shadow: 0 0 8px #f44336; }
        .status-dot.activating { background: #ff9800; box-shadow: 0 0 8px #ff9800; }
        .service-name { font-size: 14px; flex: 1; }
        .service-badge {
            font-size: 11px; padding: 2px 10px; border-radius: 12px;
            font-weight: 600; text-transform: uppercase;
        }
        .badge-active { background: #1b5e20; color: #81c784; }
        .badge-inactive { background: #b71c1c; color: #ef9a9a; }
        table {
            width: 100%; border-collapse: collapse; font-size: 13px;
        }
        th {
            text-align: left; padding: 8px 6px; color: #78909c;
            font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
            border-bottom: 1px solid #263b4a;
        }
        td { padding: 8px 6px; border-bottom: 1px solid #1e3140; }
        tr:hover td { background: rgba(79,195,247,0.05); }
        .empty-state {
            text-align: center; padding: 20px; color: #546e7a; font-size: 13px;
        }
        .log-box {
            background: #0a141e; border-radius: 6px; padding: 12px;
            font-family: "Cascadia Code", "Fira Code", monospace;
            font-size: 12px; max-height: 200px; overflow-y: auto;
            line-height: 1.6; color: #80cbc4;
        }
        .log-box::-webkit-scrollbar { width: 4px; }
        .log-box::-webkit-scrollbar-track { background: #0a141e; }
        .log-box::-webkit-scrollbar-thumb { background: #263b4a; border-radius: 2px; }
        .info-row {
            display: flex; justify-content: space-between; padding: 6px 0;
            border-bottom: 1px solid #1e3140; font-size: 13px;
        }
        .info-row .label { color: #78909c; }
        .info-row .value { color: #e0e0e0; font-weight: 500; }
        .status-summary {
            display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;
        }
        .status-item {
            display: flex; align-items: center; gap: 8px;
            padding: 8px 16px; background: #1a2a3a; border-radius: 20px;
            border: 1px solid #263b4a; font-size: 13px;
        }
        .col-2 { grid-column: span 2; }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .col-2 { grid-column: span 1; }
            .header { flex-direction: column; gap: 10px; align-items: flex-start; }
        }
    </style>
</head>
<body>
"""

HTML_FOOTER = """
    <div style="text-align: center; padding: 20px; color: #546e7a; font-size: 12px; border-top: 1px solid #1e3a4f; margin-top: 20px;">
        PXE Server Monitor · 自动刷新每 REFRESH_SECONDS 秒
    </div>
</body>
</html>
"""

def render_service_card(services):
    """渲染服务状态卡片"""
    html = '<div class="card"><div class="card-title">📡 服务状态</div>'
    for s in services:
        status = s["status"]
        dot_class = "active" if status == "active" else "inactive"
        badge_class = "badge-active" if status == "active" else "badge-inactive"
        html += f'''
        <div class="service-status">
            <span class="status-dot {dot_class}"></span>
            <span class="service-name">{s["name"].upper()}</span>
            <span class="service-badge {badge_class}">{status}</span>
        </div>'''
    html += '</div>'
    return html

def render_system_card(info):
    """渲染系统信息卡片"""
    def parse_disk(line):
        parts = line.split() if line else []
        return f"{parts[2]} / {parts[1]} ({parts[4]})" if len(parts) >= 5 else line

    def parse_mem(line):
        parts = line.split() if line else []
        return f"{parts[2]} / {parts[1]}" if len(parts) >= 3 else line

    html = '<div class="card"><div class="card-title">🖥️ 系统信息</div>'
    html += f'<div class="info-row"><span class="label">运行时间</span><span class="value">{info["uptime"][:40]}</span></div>'
    html += f'<div class="info-row"><span class="label">负载</span><span class="value">{info["load"]}</span></div>'
    html += f'<div class="info-row"><span class="label">内存</span><span class="value">{parse_mem(info["mem"])}</span></div>'
    html += f'<div class="info-row"><span class="label">磁盘</span><span class="value">{parse_disk(info["disk"])}</span></div>'
    html += '</div>'
    return html

def render_dhcp_card(leases):
    """渲染 DHCP 租约卡片"""
    html = '<div class="card col-2"><div class="card-title">🌐 DHCP 租约 <span>' + str(len(leases)) + ' 客户端</span></div>'
    if leases:
        html += '<table><tr><th>IP</th><th>MAC</th><th>主机名</th><th>到期</th></tr>'
        for l in leases[:20]:
            icon = "🟢" if l["active"] else "⚫"
            html += f'<tr><td>{icon} {l["ip"]}</td><td>{l["mac"]}</td><td>{l["hostname"] or "-"}</td><td>{l["expiry"]}</td></tr>'
        html += '</table>'
    else:
        html += '<div class="empty-state">暂无 DHCP 租约</div>'
    html += '</div>'
    return html

def render_arp_card(hosts):
    """渲染 ARP 表（网络发现）"""
    pxe_hosts = [h for h in hosts if h.get("state") == "REACHABLE"]
    html = f'<div class="card"><div class="card-title">🔍 网络发现 <span>{len(pxe_hosts)} 台在线</span></div>'
    if pxe_hosts:
        html += '<table><tr><th>IP</th><th>MAC</th></tr>'
        for h in pxe_hosts:
            html += f'<tr><td>{h["ip"]}</td><td>{h["mac"]}</td></tr>'
        html += '</table>'
    else:
        html += '<div class="empty-state">未发现其他主机</div>'
    html += '</div>'
    return html

def render_connections_card(samba_clients, nfs_clients, iscsi_sessions):
    """渲染连接信息卡片"""
    total = len(samba_clients) + len(nfs_clients) + len(iscsi_sessions)
    html = f'<div class="card"><div class="card-title">🔗 客户端连接 <span>{total} 个</span></div>'

    html += '<div style="margin-bottom: 8px;"><strong style="font-size:13px;color:#4fc3f7;">Samba</strong>'
    if samba_clients:
        for c in samba_clients:
            html += f'<div class="info-row"><span class="label">📁 {c["machine"]}</span><span class="value">{c["ip"]}</span></div>'
    else:
        html += '<div class="empty-state">无 Samba 连接</div>'
    html += '</div>'

    html += '<div style="margin-bottom: 8px;"><strong style="font-size:13px;color:#4fc3f7;">NFS</strong>'
    if nfs_clients:
        for c in nfs_clients:
            html += f'<div class="info-row"><span class="label">{c}</span></div>'
    else:
        html += '<div class="empty-state">无 NFS 客户端</div>'
    html += '</div>'

    html += '<div><strong style="font-size:13px;color:#4fc3f7;">iSCSI</strong>'
    if iscsi_sessions:
        for s in iscsi_sessions:
            html += f'<div class="info-row"><span class="label">{s}</span></div>'
    else:
        html += '<div class="empty-state">无 iSCSI 会话</div>'
    html += '</div>'

    html += '</div>'
    return html

def render_log_card(logs):
    """渲染 PXE 日志卡片"""
    html = '<div class="card col-2"><div class="card-title">📋 PXE 日志（最近30条）</div>'
    if logs:
        html += '<div class="log-box">'
        for l in logs:
            html += html_escape(l) + '\n'
        html += '</div>'
    else:
        html += '<div class="empty-state">暂无 PXE 日志</div>'
    html += '</div>'
    return html

def render_iscsi_card(targets):
    """渲染 iSCSI 目标状态"""
    html = '<div class="card"><div class="card-title">💾 iSCSI 目标</div>'
    if targets:
        for t in targets:
            name = t.get("name", "unknown").split(":")[-1].split(".")[-1] if ":" in t.get("name", "") else t.get("name", "")
            luns = t.get("luns", [])
            html += f'<div class="info-row"><span class="label">{name}</span><span class="value">{len(luns)} LUN</span></div>'
            for lun in luns:
                html += f'<div class="info-row" style="padding-left:15px;font-size:12px;"><span class="label">{lun.split("/")[-1]}</span><span class="value">{run("ls -lh " + lun + " 2>/dev/null | awk \\'{print $5}\\'", 2) or ""}</span></div>'
    else:
        html += '<div class="empty-state">无 iSCSI 目标</div>'
    html += '</div>'
    return html

def render_iso_card(mounts):
    """渲染 ISO 挂载状态"""
    html = '<div class="card"><div class="card-title">📀 ISO 挂载</div>'
    if mounts:
        for m in mounts:
            iso = m.get("iso", "").split("/")[-1] if m.get("iso") else "NFS共享"
            mount = m.get("mount", "")
            html += f'<div class="info-row"><span class="label">{iso[:30]}</span><span class="value">{"✅" if m.get("type") else "❌"}</span></div>'
            html += f'<div style="font-size:11px;color:#78909c;padding-left:10px;">{mount}</div>'
    else:
        html += '<div class="empty-state">无 ISO 挂载</div>'
    html += '</div>'
    return html

def render_tftp_card(files):
    """渲染 TFTP 文件状态"""
    html = '<div class="card"><div class="card-title">📁 TFTP 启动文件</div>'
    for name, size in files.items():
        status = "✅" if size != "missing" else "❌"
        html += f'<div class="info-row"><span class="label">{status} {name}</span><span class="value">{size if size != "missing" else "缺失"}</span></div>'
    html += '</div>'
    return html

def render_pxe_menu_card(options):
    """渲染 PXE 菜单选项"""
    html = '<div class="card"><div class="card-title">📋 PXE 启动菜单</div>'
    if options:
        for opt in options:
            html += f'<div class="info-row"><span class="label">{opt.get("key", "?")}</span><span class="value">{opt.get("label", "").replace("^", "")}</span></div>'
    else:
        html += '<div class="empty-state">无菜单配置</div>'
    html += '</div>'
    return html

def render_netcard_card(speed):
    """渲染网络带宽和客户端连接卡片"""
    html = '<div class="card"><div class="card-title">🌐 网络带宽 & 客户端</div>'
    # Total bandwidth
    html += f'<div style="text-align:center;padding:6px 0 10px 0;border-bottom:1px solid #1e3140;">'
    html += f'<span style="font-size:24px;color:#4fc3f7;">⬇ {speed.get("rx", "0 KB/s")}</span>'
    html += f'<span style="font-size:13px;color:#78909c;margin:0 8px;">|</span>'
    html += f'<span style="font-size:14px;color:#a5d6a7;">⬆ {speed.get("tx", "0 KB/s")}</span>'
    html += '</div>'
    # Per-service connections
    for svc, count in speed.get("services", {}).items():
        html += f'<div class="info-row"><span class="label">{svc}</span><span class="value">{count} 连接</span></div>'
    # Client IPs
    ips = speed.get("client_ips", [])
    if ips:
        html += '<div style="margin-top:8px;border-top:1px solid #1e3140;padding-top:8px;"><span style="font-size:12px;color:#78909c;">客户端 IP:</span></div>'
        for ip in ips[:6]:
            html += f'<div class="info-row" style="font-size:12px;"><span class="label">🔗 {ip}</span></div>'
    else:
        html += '<div class="empty-state">无活跃客户端</div>'
    html += '</div>'
    return html

def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ===== HTTP 处理器 =====

class MonitorHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/status":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                try:
                    data = {
                        "services": {
                            "dnsmasq": check_service("dnsmasq"),
                            "nfs": check_service("nfs-kernel-server"),
                            "smb": check_service("smbd"),
                            "tgt": check_service("tgt"),
                        },
                        "dhcp_leases": get_dhcp_leases(),
                        "arp_hosts": get_arp_table(),
                        "samba_clients": get_samba_connections(),
                        "nfs_clients": get_nfs_clients(),
                        "iscsi_sessions": get_iscsi_sessions(),
                        "system": get_system_info(),
                        "download": "",
                        "pxe_log": get_pxe_log(),
                        "iscsi_targets": get_iscsi_info(),
                        "iso_mounts": get_iso_mounts(),
                        "tftp_files": get_tftp_summary(),
                        "menu_options": get_pxe_menu_options(),
                        "nfs_clients_info": get_nfs_clients_info(),
                        "net_speed": get_network_speed(),
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                except Exception as e:
                    data = {"error": str(e), "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

                self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
                return

            # Serve HTML page
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            html = self.render_page()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            # Last-resort error page
            try:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Server Error: {e}".encode())
            except:
                pass

    def render_page(self):
        try:
            services = [
                check_service("dnsmasq"),
                check_service("nfs-kernel-server"),
                check_service("smbd"),
                check_service("tgt"),
            ]
            leases = get_dhcp_leases()
            hosts = get_arp_table()
            samba_clients = get_samba_connections()
            nfs_clients = get_nfs_clients()
            iscsi_sessions = get_iscsi_sessions()
            sysinfo = get_system_info()
            logs = get_pxe_log()
            iscsi_targets = get_iscsi_info()
            iso_mounts = get_iso_mounts()
            tftp_files = get_tftp_summary()
            menu_options = get_pxe_menu_options()
            net_speed = get_network_speed()
        except Exception as e:
            # If any data collection fails, return a minimal page
            services = [
                {"name": "dnsmasq", "status": "unknown", "enabled": "unknown"},
                {"name": "nfs", "status": "unknown", "enabled": "unknown"},
                {"name": "smb", "status": "unknown", "enabled": "unknown"},
                {"name": "tgt", "status": "unknown", "enabled": "unknown"},
            ]
            leases = []
            hosts = []
            samba_clients = []
            nfs_clients = []
            iscsi_sessions = []
            sysinfo = {"uptime": "N/A", "disk": "N/A", "mem": "N/A", "load": "N/A"}
            logs = []

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = HTML_HEADER.replace("REFRESH_SECONDS", str(REFRESH_SECONDS))

        # Header
        html += f'''
        <div class="header">
            <h1>🖥️ PXE 服务器监控 <small>192.168.1.14</small></h1>
            <span class="time">🕐 {now}</span>
        </div>
        '''

        # Status summary bar
        active_count = sum(1 for s in services if s["status"] == "active")
        html += f'''
        <div class="status-summary">
            <div class="status-item"><span class="status-dot active"></span> {active_count}/{len(services)} 服务运行中</div>
            <div class="status-item">📡 {len(leases)} DHCP 租约</div>
            <div class="status-item">🔍 {len([h for h in hosts if h.get("state")=="REACHABLE"])} 主机在线</div>
            <div class="status-item">💾 {len(iscsi_targets)} iSCSI 目标</div>
            <div class="status-item">📀 {len(iso_mounts)} ISO 已挂载</div>

        </div>
        '''

        # Grid
        html += '<div class="grid">'
        html += render_service_card(services)
        html += render_system_card(sysinfo)

        html += render_arp_card(hosts)
        html += render_connections_card(samba_clients, nfs_clients, iscsi_sessions)
        html += '</div>'

        # PXE 状态行
        html += '<div class="grid">'
        html += render_iscsi_card(iscsi_targets)
        html += render_iso_card(iso_mounts)
        html += render_tftp_card(tftp_files)
        html += render_pxe_menu_card(menu_options)
        html += render_netcard_card(net_speed)
        html += '</div>'

        # Full-width cards
        html += '<div class="grid">'
        html += render_dhcp_card(leases)
        html += render_log_card(logs)
        html += '</div>'

        html += HTML_FOOTER.replace("REFRESH_SECONDS", str(REFRESH_SECONDS))
        return html

    def log_message(self, format, *args):
        """静默访问日志"""
        pass


# ===== 启动服务器 =====

if __name__ == "__main__":
    server = http.server.HTTPServer((HOST, PORT), MonitorHandler)
    print(f"📊 PXE 监控面板启动成功!")
    print(f"   http://{HOST}:{PORT}")
    print(f"   自动刷新: 每 {REFRESH_SECONDS} 秒")
    print(f"   API: http://{HOST}:{PORT}/api/status")
    print(f"   按 Ctrl+C 停止")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n监控面板已停止")
        server.server_close()
