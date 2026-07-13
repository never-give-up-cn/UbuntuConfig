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

# ===== 监控命令定义 =====

def run(cmd, timeout=5):
    """执行 shell 命令，返回输出"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""

def run_sudo(cmd, timeout=5):
    """使用 sudo 执行命令。返回空字符串超时或失败"""
    return run(f'echo "1" | sudo -S timeout {timeout} {cmd} 2>/dev/null || true', timeout + 2)

def run_timeout(cmd, timeout=5):
    """用 timeout 命令包裹，确保不卡死"""
    return run(f'timeout {timeout} {cmd} 2>/dev/null || true', timeout + 2)

def check_service(name):
    """检查 systemd 服务状态"""
    status = run_timeout(f"systemctl is-active {name}", 3)
    enabled = run_timeout(f"systemctl is-enabled {name} 2>/dev/null", 3)
    return {"name": name, "status": status or "inactive", "enabled": enabled or "unknown"}

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
    log_file = "/var/log/pxe/dnsmasq.log"
    if os.path.exists(log_file):
        with open(log_file) as f:
            lines = f.readlines()
            for line in lines[-30:]:
                logs.append(line.strip())
    return logs

def get_arp_table():
    """获取 ARP 表（发现网络上的主机）"""
    hosts = []
    out = run("arp -n 2>/dev/null || ip neigh show 2>/dev/null")
    if out:
        for line in out.split("\n"):
            if line.strip():
                parts = line.split()
                if len(parts) >= 4 and "incomplete" not in line:
                    hosts.append({
                        "ip": parts[0],
                        "mac": parts[2] if len(parts) > 2 else "",
                        "state": parts[-1] if parts[-1] in ["REACHABLE", "STALE", "DELAY"] else "reachable"
                    })
    return hosts

def get_download_progress():
    """获取 aMule 下载进度"""
    out = run_timeout("amulecmd -P '1' -c 'show dl' 2>&1", 8)
    if not out:
        out = run_timeout("ps aux | grep amuled | grep -v grep || true", 3)
        if out:
            return "aMule 运行中 (amulecmd 无响应)"
        return "aMule 未运行"
    # Extract just the useful info
    lines = out.split("\n")
    useful = [l for l in lines if ".iso" in l or "[" in l or "Download" in l or "Waiting" in l]
    return "\n".join(useful[-5:]) if useful else out[:200]

def get_system_info():
    """获取系统信息"""
    uptime = run("uptime -p 2>/dev/null || uptime")
    disk = run("df -h / | tail -1")
    mem = run("free -h | grep Mem")
    load = run("cat /proc/loadavg | cut -d' ' -f1-3")
    return {"uptime": uptime, "disk": disk, "mem": mem, "load": load}

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
    pxe_hosts = [h for h in hosts if h["state"] == "REACHABLE"]
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

def render_download_card(progress):
    """渲染下载进度卡片"""
    html = '<div class="card"><div class="card-title">⬇️ Windows 11 ISO 下载</div>'
    if progress:
        html += f'<div class="log-box" style="max-height:none;font-size:13px;">{progress}</div>'
    else:
        html += '<div class="empty-state">aMule 未运行</div>'
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
                            "amule": {"name": "amule", "status": "active" if run("pgrep amuled 2>/dev/null", 2) else "inactive"}
                        },
                        "dhcp_leases": get_dhcp_leases(),
                        "arp_hosts": get_arp_table(),
                        "samba_clients": get_samba_connections(),
                        "nfs_clients": get_nfs_clients(),
                        "iscsi_sessions": get_iscsi_sessions(),
                        "system": get_system_info(),
                        "download": get_download_progress(),
                        "pxe_log": get_pxe_log(),
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
                {"name": "amule", "status": "active" if run("pgrep amuled 2>/dev/null", 2) else "inactive"}
            ]
            leases = get_dhcp_leases()
            hosts = get_arp_table()
            samba_clients = get_samba_connections()
            nfs_clients = get_nfs_clients()
            iscsi_sessions = get_iscsi_sessions()
            sysinfo = get_system_info()
            dl_progress = get_download_progress()
            logs = get_pxe_log()
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
            dl_progress = f"数据采集失败: {e}"
            logs = []

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = HTML_HEADER.replace("REFRESH_SECONDS", str(REFRESH_SECONDS))

        # Header
        html += f'''
        <div class="header">
            <h1>🖥️ PXE 服务器监控 <small>192.168.183.131</small></h1>
            <span class="time">🕐 {now}</span>
        </div>
        '''

        # Status summary bar
        active_count = sum(1 for s in services if s["status"] == "active")
        html += f'''
        <div class="status-summary">
            <div class="status-item"><span class="status-dot active"></span> {active_count}/{len(services)} 服务运行中</div>
            <div class="status-item">📡 {len(leases)} DHCP 租约</div>
            <div class="status-item">🔍 {len([h for h in hosts if h["state"]=="REACHABLE"])} 主机在线</div>
            <div class="status-item">⬇️ {dl_progress[:50] if dl_progress else "等待下载..."}</div>
        </div>
        '''

        # Grid
        html += '<div class="grid">'
        html += render_service_card(services)
        html += render_system_card(sysinfo)
        html += render_download_card(dl_progress)
        html += render_arp_card(hosts)
        html += render_connections_card(samba_clients, nfs_clients, iscsi_sessions)
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
