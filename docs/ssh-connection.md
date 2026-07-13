# SSH 连接记录

## 连接方式

使用 Python paramiko 库进行 SSH 连接（非交互式）：

```python
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.183.131", 22, "pi", "1",
               timeout=20, look_for_keys=False, allow_agent=False)
stdin, stdout, stderr = client.exec_command("command")
print(stdout.read().decode())
client.close()
```

## 连接参数

| 参数 | 值 |
|------|-----|
| IP | 192.168.183.131 |
| 端口 | 22 |
| 用户名 | pi |
| 密码 | 1 |

## 注意事项

1. **MaxStartups 限制**：OpenSSH 服务器默认限制短时间内未认证连接数。连续失败后需等待 30-60 秒。
2. **连接间隔**：每次连接后建议间隔至少 3 秒。
3. **主机密钥指纹**：`SHA256:O5ySIS29umaZFQoELneOYpBOkIy46obL6gjAqZH4Yxs` (ED25519)

## 故障排除

| 现象 | 原因 | 解决 |
|------|------|------|
| "Not allowed at this time" | MaxStartups 限制 | 等待 30-60 秒重试 |
| "Authentication timeout" | 认证响应慢或密码错误 | 检查密码，延长 timeout |
| "Connection reset" | 连接频率过高 | 减少连接频率 |
