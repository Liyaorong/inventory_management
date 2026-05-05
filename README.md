# 每日加工库存系统

基于 Flask + SQLAlchemy 的加工库存台账系统。本地开发默认使用 SQLite，生产部署使用 PostgreSQL。

## 本地开发

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

启动后访问 `http://127.0.0.1:5000`。

同一 Wi-Fi/局域网内的手机也可以访问。启动后先在电脑上查看本机 IPv4 地址：

```powershell
ipconfig
```

找到当前联网网卡的 `IPv4 地址`，例如 `192.168.1.23`，然后在手机浏览器访问：

```text
http://192.168.1.23:5000
```

如果手机打不开：

- 确认手机和电脑连接的是同一个 Wi-Fi/局域网。
- 确认电脑端程序仍在运行。
- Windows 防火墙可能拦截了 Python/5000 端口，需要允许 Python 通过专用网络，或放行 TCP `5000` 端口。
- 不建议把 Flask 开发服务器直接暴露到公网；公网或长期使用请按下面的生产部署方式通过 Gunicorn + Nginx 部署。

首次使用创建管理员：

```bash
flask --app app:create_app create-admin
```

## 生产环境变量

生产环境必须设置：

```bash
SECRET_KEY=替换为强随机字符串
DATABASE_URL=postgresql+psycopg://inventory_user:强密码@127.0.0.1:5432/inventory_db
AUTO_CREATE_DB=0
```

## 阿里云 Ubuntu 22.04 部署

本项目建议作为内部系统部署：业务入口只绑定 Tailscale/ZeroTier 内网 IP，不直接开放公网业务端口。

### 1. 准备服务器

购买阿里云 ECS 或轻量应用服务器，系统选择 Ubuntu 22.04 LTS。安全组建议只开放：

- SSH：`22/tcp`，最好限制为你的办公 IP
- Tailscale/ZeroTier 所需出站访问
- 不开放公网 `80/443`，除非后续改为公网域名部署

登录服务器后先执行基础初始化：

```bash
cd /tmp
sudo apt update
sudo apt install -y python3-venv python3-pip postgresql nginx git
sudo adduser --system --group --home /opt/inventory-app inventory || true
sudo mkdir -p /opt/inventory-app/app /etc/inventory-app /var/backups/inventory-app
sudo chown -R inventory:inventory /opt/inventory-app
sudo chmod 750 /etc/inventory-app
sudo chmod 700 /var/backups/inventory-app
```

### 2. 创建 PostgreSQL 数据库

替换下面的 `强数据库密码`：

```bash
sudo -u postgres psql
```

进入 PostgreSQL 后执行：

```sql
CREATE USER inventory_user WITH PASSWORD '强数据库密码';
CREATE DATABASE inventory_db OWNER inventory_user;
\q
```

PostgreSQL 默认只监听本机，保持这个设置即可。

### 3. 上传代码

把本项目目录上传到服务器：

```bash
/opt/inventory-app/app
```

不要上传本机的 `.venv`、`.idea`、`__pycache__`、`instance/inventory.db`。

### 4. 配置环境变量

创建生产环境配置：

```bash
cd /opt/inventory-app/app
sudo cp deploy/.env.example /etc/inventory-app/inventory.env
sudo nano /etc/inventory-app/inventory.env
sudo chmod 640 /etc/inventory-app/inventory.env
```

必须修改：

```bash
SECRET_KEY=强随机字符串
DATABASE_URL=postgresql+psycopg://inventory_user:强数据库密码@127.0.0.1:5432/inventory_db
AUTO_CREATE_DB=0
FLASK_DEBUG=0
```

生成 `SECRET_KEY`：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 5. 安装依赖并初始化数据库

```bash
cd /opt/inventory-app/app
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
set -a
. /etc/inventory-app/inventory.env
set +a
flask --app app:app db upgrade
flask --app app:app create-admin
sudo chown -R inventory:inventory /opt/inventory-app/app
```

### 6. 启用 Gunicorn systemd 服务

```bash
sudo cp /opt/inventory-app/app/deploy/inventory.service /etc/systemd/system/inventory.service
sudo systemctl daemon-reload
sudo systemctl enable --now inventory
sudo systemctl status inventory
```

### 7. 配置 Nginx 内网访问

先查看服务器的 Tailscale/ZeroTier 内网 IP。然后编辑：

```bash
sudo cp /opt/inventory-app/app/deploy/inventory.nginx.conf /etc/nginx/sites-available/inventory
sudo nano /etc/nginx/sites-available/inventory
```

把示例里的 `100.64.0.10` 改成服务器的内网 IP。

启用站点：

```bash
sudo ln -sf /etc/nginx/sites-available/inventory /etc/nginx/sites-enabled/inventory
sudo nginx -t
sudo systemctl reload nginx
```

然后从已接入 Tailscale/ZeroTier 的电脑访问：

```text
http://服务器内网IP/
```

### 8. 配置数据库备份

```bash
sudo cp /opt/inventory-app/app/deploy/backup_postgres.sh /usr/local/bin/inventory-backup
sudo chmod +x /usr/local/bin/inventory-backup
sudo inventory-backup
```

添加每天凌晨 2 点自动备份：

```bash
sudo crontab -e
```

加入：

```cron
0 2 * * * /usr/local/bin/inventory-backup >> /var/log/inventory-backup.log 2>&1
```

备份文件保存在：

```text
/var/backups/inventory-app
```

### 常用维护命令

查看应用日志：

```bash
sudo journalctl -u inventory -f
```

重启应用：

```bash
sudo systemctl restart inventory
```

更新代码后执行：

```bash
cd /opt/inventory-app/app
. .venv/bin/activate
pip install -r requirements.txt
set -a
. /etc/inventory-app/inventory.env
set +a
flask --app app:app db upgrade
sudo chown -R inventory:inventory /opt/inventory-app/app
sudo systemctl restart inventory
```
