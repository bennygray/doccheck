# 围标检测系统 · Linux 生产部署指南

**适用**:CentOS 7(主路径) · Ubuntu 22.04 / Debian 12 / Rocky 9(侧边注)

**目标**:从裸服务器 →HTTPS 公网上线,全部依赖走国内镜像加速

**估时**:熟练 40 分钟;第一次照操作约 1.5~2 小时(首次拉镜像 + 证书申请会占时间)

> ⚠️ CentOS 7 已于 2024-06-30 EOL,官方 yum 仓库已下线,所有 repo 必须切到**阿里云 vault 镜像**。长期建议迁到 Rocky 9 / 阿里云 Linux 3,但本文档照顾 CentOS 7 现存环境。

---

## 目录

- [0. 检查清单](#0-检查清单)
- [1. 服务器规格 & 预检](#1-服务器规格--预检)
- [2. 系统准备(CentOS 7)](#2-系统准备centos-7)
- [3. 安装 Docker CE](#3-安装-docker-ce)
- [4. 防火墙 firewalld](#4-防火墙-firewalld)
- [5. 拉代码 + 改 Dockerfile](#5-拉代码--改-dockerfile-国内源)
- [6. 配置 .env](#6-配置-env)
- [7. 生产编排 override](#7-生产编排-override)
- [8. 首次启动(关键顺序)](#8-首次启动关键顺序)
- [9. nginx 反代](#9-宿主-nginx-反代)
- [10. HTTPS 证书](#10-https-证书)
- [11. 上线验证清单](#11-上线验证清单)
- [12. 首次登录 + LLM 配置](#12-首次登录--llm-配置)
- [13. 日常运维](#13-日常运维)
- [14. 常见问题](#14-常见问题)
- [附录](#附录)

---

## 0. 检查清单

部署前确认:

- [ ] 服务器可访问公网(能 ping `mirrors.aliyun.com`)
- [ ] 至少 1 个域名解析到本机公网 IP(例如 `doccheck.yourdomain.com` → 公网 IP)
- [ ] 有 root 或 sudo 权限
- [ ] 已有 LLM API Key(DeepSeek / 通义千问 / 你自建 AIGC 代理都行,必须是 **OpenAI 兼容格式**)

部署后验证:

- [ ] `https://你的域名` 能正常打开登录页
- [ ] 登录 admin,被强制改密
- [ ] 管理后台 → LLM 配置,点"测试连接"返回成功
- [ ] 上传一个测试项目,能走完一次检测

---

## 1. 服务器规格 & 预检

| 项 | 最低 | 推荐 |
|---|---|---|
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 40 GB | 60 GB+ SSD |
| 出站 | 3 Mbps | 5 Mbps |

预检命令:

```bash
uname -a && cat /etc/os-release    # 确认 CentOS 7.x
free -h                             # 内存
df -h /                             # 磁盘
ping -c 3 mirrors.aliyun.com        # 出网
```

预期:`PRETTY_NAME="CentOS Linux 7 (Core)"` + 内存 ≥ 4G + 根分区空闲 ≥ 40G + ping 通。

---

## 2. 系统准备(CentOS 7)

### 2.1 切 yum 源到阿里云 vault

**必做**。CentOS 7 官方源已下线,默认 repo 现在全部 404。

```bash
# 备份现有 repo 文件
sudo mkdir -p /etc/yum.repos.d/backup
sudo mv /etc/yum.repos.d/CentOS-*.repo /etc/yum.repos.d/backup/ 2>/dev/null || true

# 下载阿里云 vault 版 Base 源(指向 CentOS 7.9.2009 的 vault)
sudo curl -fsSL -o /etc/yum.repos.d/CentOS-Base.repo \
  https://mirrors.aliyun.com/repo/Centos-vault-7.9.2009.repo

# EPEL 源(装 nginx / certbot 等要用)
sudo curl -fsSL -o /etc/yum.repos.d/epel.repo \
  https://mirrors.aliyun.com/repo/epel-7.repo

# 清缓存 + 重建
sudo yum clean all
sudo yum makecache fast
```

验证(应该能看到 `updates`、`extras`、`base`、`epel` 四个 repo 都生成了缓存):

```bash
sudo yum repolist
```

### 2.2 基础工具

```bash
sudo yum install -y \
  curl wget git vim unzip \
  yum-utils ca-certificates \
  device-mapper-persistent-data lvm2 \
  chrony
```

### 2.3 时区 + 时间同步

时间漂移会导致 JWT 过期异常和 Let's Encrypt 证书验证失败。

```bash
sudo timedatectl set-timezone Asia/Shanghai

sudo systemctl enable --now chronyd
chronyc sources       # 应看到 ^* 开头的 NTP 服务器
```

### 2.4 创建部署用户(可选,但建议)

```bash
sudo adduser deploy
sudo passwd deploy
sudo usermod -aG wheel deploy    # CentOS 用 wheel 组拿 sudo
su - deploy
```

以下步骤默认以 `deploy` 用户操作。需要 root 的会加 `sudo`。

### 2.5 SELinux 检查

```bash
getenforce
```

- **返回 `Disabled` 或 `Permissive`** → 直接跳过
- **返回 `Enforcing`** → 先不管,等到后面 docker volume 出权限问题再放开(§14 FAQ 有处理步骤)

---

> **Ubuntu / Debian / Rocky 用户差异速查**
> - 2.1 换成:`sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list && sudo apt-get update`
> - 2.2 换成:`sudo apt-get install -y curl wget git vim unzip ca-certificates gnupg lsb-release`
> - 2.4 用 `usermod -aG sudo deploy`(sudo 组,不是 wheel)
> - 其余一致

---

## 3. 安装 Docker CE

### 3.1 卸载旧版(若有)

```bash
sudo yum remove -y \
  docker docker-common docker-selinux docker-engine \
  podman runc 2>/dev/null || true
```

### 3.2 阿里云 Docker CE 源 + 安装

```bash
sudo yum-config-manager --add-repo \
  https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo

sudo yum makecache fast

sudo yum install -y \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

> `docker-compose-plugin` 是 compose v2 插件形式(命令为 `docker compose`,**带空格**),替代老版本 `docker-compose`(带连字符)。本文档所有命令都用 v2 写法。

### 3.3 启动 + 开机自启 + 免 sudo

```bash
sudo systemctl enable --now docker

sudo usermod -aG docker $USER
newgrp docker

docker --version           # Docker version 27.x.x
docker compose version     # Docker Compose version v2.x.x
```

### 3.4 配置 Docker Registry 镜像加速

**必做**。不然 `postgres:16-alpine` 等 Docker Hub 镜像在国内会拉不下来。

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com",
    "https://docker.nju.edu.cn",
    "https://docker.mirrors.sjtug.sjtu.edu.cn"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "20m",
    "max-file": "5"
  },
  "storage-driver": "overlay2",
  "live-restore": true
}
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

验证:

```bash
docker info | grep -A5 "Registry Mirrors"
# 应看到 4 个 https://... 地址

docker run --rm hello-world
# 应看到 "Hello from Docker!" 输出
```

> 如果 4 个都超时,去 https://cr.console.aliyun.com/cn-hangzhou/instances/mirrors 领阿里云自己的专属加速器 URL(格式 `https://xxx.mirror.aliyuncs.com`),填进 `registry-mirrors` 数组第一位。

---

## 4. 防火墙 firewalld

```bash
sudo systemctl enable --now firewalld

sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http      # 80
sudo firewall-cmd --permanent --add-service=https     # 443
sudo firewall-cmd --reload

sudo firewall-cmd --list-all
# 应看到 services: ssh http https
```

**注意**:不要放开 5173 / 8000 / 5432,这些只在服务器内网(loopback + docker 内部网络)使用。

---

## 5. 拉代码 + 改 Dockerfile 国内源

### 5.1 Clone 仓库

```bash
mkdir -p ~/apps && cd ~/apps

git clone https://github.com/bennygray/doccheck.git
cd doccheck
git checkout v0.2.0       # 锁定到发布版本(当前最新)

ls                         # 应看到 backend/ frontend/ docker-compose.yml 等
```

如果 `git clone` 超时或慢,走 ghproxy 兜底:

```bash
git clone https://ghproxy.com/https://github.com/bennygray/doccheck.git
```

### 5.2 改 `backend/Dockerfile`(pip 走清华源)

仓库默认的 Dockerfile 用 GHCR 拉 `uv`,pip 也走官方 PyPI,国内会慢。替换成下面版本:

```bash
cat > backend/Dockerfile <<'EOF'
FROM python:3.12-slim

WORKDIR /app

# 国内 pip / uv 镜像源
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# debian 12 (python:3.12-slim 基础) 的 apt 源也切阿里云
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g; \
            s|http://security.debian.org|https://mirrors.aliyun.com|g' \
    /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# 直接用 pip 装 uv,避免 GHCR 不稳
RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system -r pyproject.toml

COPY . .

# 生产模式:不带 --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF
```

### 5.3 改 `frontend/Dockerfile.prod`(npm 走淘宝源,多阶段构建)

生产**强烈建议**用 nginx 托管静态 dist,而不是跑 Vite dev server。新增生产专用 Dockerfile:

```bash
cat > frontend/Dockerfile.prod <<'EOF'
# ==== builder 阶段:npm build ====
FROM node:22-alpine AS builder
WORKDIR /app

# alpine apk 走阿里云
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories

# npm 走淘宝源
RUN npm config set registry https://registry.npmmirror.com

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build        # 产物到 /app/dist

# ==== runtime 阶段:nginx 托管 dist ====
FROM nginx:alpine
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories

# 清掉默认站点
RUN rm -f /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EOF
```

对应的容器内 nginx 配置(**给容器用**的,宿主 nginx 另写,§9):

```bash
cat > frontend/nginx.conf <<'EOF'
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  client_max_body_size 200m;

  # SPA fallback:未匹配路径都回 index.html
  location / {
    try_files $uri $uri/ /index.html;
  }

  # API 反代到 backend 容器
  location /api/ {
    proxy_pass http://backend:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE / WebSocket 必需
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
  }
}
EOF
```

---

## 6. 配置 .env

仓库根目录创建 `.env`(docker compose 自动加载):

```bash
cd ~/apps/doccheck

cat > .env <<'EOF'
# ==================== LLM(首次启动的 fallback,正式值请登录后用管理员 UI 配) ====================
LLM_PROVIDER=custom
LLM_API_KEY=sk-这里填你的真实 API Key
LLM_MODEL=deepseek-v3.2
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_TIMEOUT_S=30

# ==================== 数据库(compose 内部使用,一般不改,密码请改强) ====================
POSTGRES_DB=documentcheck
POSTGRES_USER=postgres
POSTGRES_PASSWORD=请改成强密码-AtLeast16Chars

# ==================== 管理员初始口令(首次启动 seed) ====================
# 登录后会强制改密,这里只是首登凭据
AUTH_SEED_ADMIN_USERNAME=admin
AUTH_SEED_ADMIN_PASSWORD=请改成强密码-InitOnly

# ==================== CORS(替换为你的真实域名) ====================
CORS_ORIGINS=https://doccheck.yourdomain.com
EOF

chmod 600 .env
```

**安全红线**:

- `.env` 含密码和 API Key,权限已设 `600`,只有当前用户可读
- `.env` 已在仓库 `.gitignore` 里,**永远不要 commit**
- `LLM_*` 在 `.env` 里填的只是首次启动兜底;登录后在管理后台改,改后值写进 `system_configs` 表,进程重启也不丢

编辑完后核对一次:

```bash
cat .env | grep -E "^(LLM_API_KEY|POSTGRES_PASSWORD|AUTH_SEED_ADMIN_PASSWORD|CORS_ORIGINS)=" | sed 's/=.*/= [已配置]/'
```

---

## 7. 生产编排 override

仓库自带的 `docker-compose.yml` 是**开发模式**(有 `--reload`、bind-mount 源码、DB 端口对外)。不动它,新增一个生产 override:

```bash
cd ~/apps/doccheck

cat > docker-compose.prod.yml <<'EOF'
services:
  db:
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    # 生产不把 5432 暴露到主机,只走 compose 内部网络
    ports: []

  backend:
    restart: unless-stopped
    # 覆盖 dev 的 --reload CMD
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      DEBUG: "false"
      LLM_PROVIDER: ${LLM_PROVIDER}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL}
      LLM_BASE_URL: ${LLM_BASE_URL}
      LLM_TIMEOUT_S: ${LLM_TIMEOUT_S:-30}
      AUTH_SEED_ADMIN_USERNAME: ${AUTH_SEED_ADMIN_USERNAME}
      AUTH_SEED_ADMIN_PASSWORD: ${AUTH_SEED_ADMIN_PASSWORD}
      CORS_ORIGINS: ${CORS_ORIGINS}
      LIFECYCLE_DRY_RUN: "false"
    # 生产镜像内已有代码,不需要 bind mount;只留 uploads volume
    volumes:
      - uploads:/app/uploads
    # 不对外暴露 :8000,由容器间网络和宿主 nginx 访问
    ports: []

  frontend:
    restart: unless-stopped
    build:
      context: ./frontend
      dockerfile: Dockerfile.prod       # 用 §5.3 新建的生产 Dockerfile
    # 只对 loopback 暴露 80,宿主 nginx 反代上去
    ports:
      - "127.0.0.1:5173:80"
    depends_on:
      - backend
    volumes: []
    environment: {}

volumes:
  uploads:
  pgdata:
EOF
```

---

## 8. 首次启动(关键顺序)

**顺序非常重要**:先起 DB 等健康 → 跑 alembic 迁移 → 再起全家。直接 `up -d` 会因迁移没跑导致 backend 报表不存在。

```bash
cd ~/apps/doccheck

# 8.1 构建镜像(首次 10~20 分钟,主要卡在 npm install + pip install)
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# 8.2 先起 DB,等 healthy
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d db

# 看 DB 日志,看到 "database system is ready to accept connections" 后 Ctrl+C
docker compose logs -f db

# 确认 healthy
docker compose ps db
# 应显示:doccheck-db-1   Up XX seconds (healthy)

# 8.3 跑 alembic 迁移(最关键的一步)
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head

# 应看到多行 "Running upgrade xxx -> yyy" 最终无错误返回

# 8.4 启动全部
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 确认三个容器都健康
docker compose ps
# 应显示:
# doccheck-db-1        Up XX seconds (healthy)
# doccheck-backend-1   Up XX seconds (healthy)
# doccheck-frontend-1  Up XX seconds
```

### 8.5 容器内部健康检查

```bash
# 后端(从容器内访问,因为 :8000 不对外)
docker compose exec backend curl -sS http://127.0.0.1:8000/api/health
# 应返回:{"status":"ok","db":"ok"}

# 前端静态 dist(通过 loopback 映射)
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/
# 应返回:200

# 前端能代理到后端
curl -sS http://127.0.0.1:5173/api/health
# 应返回:{"status":"ok","db":"ok"}
```

全部通过就算容器层成功。下一步是宿主 nginx + HTTPS。

---

## 9. 宿主 nginx 反代

服务器上再跑一层 nginx,对外 443 HTTPS,往 127.0.0.1:5173 转发。

### 9.1 安装 nginx + certbot(CentOS 7)

```bash
# nginx 官方源(阿里云镜像)
sudo tee /etc/yum.repos.d/nginx.repo > /dev/null <<'EOF'
[nginx-stable]
name=nginx stable repo
baseurl=https://mirrors.aliyun.com/nginx/centos/7/$basearch/
gpgcheck=0
enabled=1
EOF

sudo yum install -y nginx certbot python2-certbot-nginx

sudo systemctl enable --now nginx
```

### 9.2 站点配置(临时用 80 走 certbot HTTP 挑战,443 稍后由 certbot 自动加)

```bash
sudo mkdir -p /etc/nginx/conf.d
sudo mkdir -p /var/www/certbot

sudo tee /etc/nginx/conf.d/doccheck.conf > /dev/null <<'EOF'
server {
  listen 80;
  server_name doccheck.yourdomain.com;      # 替换为你的域名

  # certbot HTTP-01 验证路径
  location /.well-known/acme-challenge/ {
    root /var/www/certbot;
  }

  client_max_body_size 200m;

  # 首次(没证书前)直接反代 80 → 容器 5173
  # 装完证书后 certbot 会自动加 443 server 块并把这里改成 301 重定向
  location / {
    proxy_pass http://127.0.0.1:5173;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE / WebSocket
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
  }
}
EOF

# 测试配置语法
sudo nginx -t

# 重载
sudo systemctl reload nginx
```

**先用 HTTP 访问验证通路**:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://doccheck.yourdomain.com/api/health
# 应返回:200
```

如果 200,说明:DNS → 宿主 nginx → 容器 → 后端,一条链打通。

---

## 10. HTTPS 证书

### 10.1 Let's Encrypt(首选,免费自动续签)

```bash
sudo certbot --nginx \
  -d doccheck.yourdomain.com \
  --agree-tos \
  --email you@example.com \
  --no-eff-email \
  --redirect
```

- `--nginx`:自动改 nginx 配置加 443 server
- `--redirect`:自动把 80 → 443 重定向
- 成功后会看到 `Congratulations! Your certificate ...`

**自动续签**(certbot 默认装 systemd timer):

```bash
sudo systemctl list-timers | grep certbot
# 应显示类似 certbot-renew.timer ... 每天两次

# 手工测试续签(不真签)
sudo certbot renew --dry-run
```

### 10.2 兜底:用阿里云/腾讯云 DV 证书

如果服务器拉不到 Let's Encrypt(极少见,DNS 抽风时):

1. 去阿里云 SSL 证书控制台申请免费 DV 证书(1 年)
2. 下载 nginx 格式,得到 `fullchain.pem` + `private.key`
3. 传到服务器:

```bash
sudo mkdir -p /etc/nginx/ssl
sudo mv fullchain.pem /etc/nginx/ssl/
sudo mv private.key /etc/nginx/ssl/
sudo chmod 600 /etc/nginx/ssl/private.key
```

4. 手工改 `/etc/nginx/conf.d/doccheck.conf`,加 443 server 块:

```nginx
server {
  listen 443 ssl http2;
  server_name doccheck.yourdomain.com;

  ssl_certificate     /etc/nginx/ssl/fullchain.pem;
  ssl_certificate_key /etc/nginx/ssl/private.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_ciphers HIGH:!aNULL:!MD5;

  client_max_body_size 200m;

  location / {
    proxy_pass http://127.0.0.1:5173;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
  }
}

# 把原来的 80 server 改成重定向
server {
  listen 80;
  server_name doccheck.yourdomain.com;
  location /.well-known/acme-challenge/ { root /var/www/certbot; }
  location / { return 301 https://$host$request_uri; }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 11. 上线验证清单

按顺序测一遍:

```bash
# 1. TLS 有效
curl -sS -o /dev/null -w "TLS: %{http_code}\n" https://doccheck.yourdomain.com/

# 2. 证书信息
echo | openssl s_client -servername doccheck.yourdomain.com -connect doccheck.yourdomain.com:443 2>/dev/null | openssl x509 -noout -dates

# 3. 后端健康
curl -sS https://doccheck.yourdomain.com/api/health

# 4. 80 → 443 重定向
curl -sSI http://doccheck.yourdomain.com/ | head -3
```

预期:

1. `200`
2. 看到 `notBefore` / `notAfter` 日期,`notAfter` 在未来
3. `{"status":"ok","db":"ok"}`
4. `HTTP/1.1 301 Moved Permanently` + `Location: https://...`

全通过即上线成功。

---

## 12. 首次登录 + LLM 配置

1. 浏览器打开 `https://doccheck.yourdomain.com`
2. 用 `.env` 里的 `AUTH_SEED_ADMIN_USERNAME`(默认 `admin`)和 `AUTH_SEED_ADMIN_PASSWORD` 登录
3. **系统强制改密**,改一个强密码并记下来
4. 进 **管理后台 → LLM 配置**
5. 填真实的:
   - Provider:`custom` / `deepseek` / `dashscope`
   - Base URL:例如 `https://api.deepseek.com/v1`
   - API Key:你的真实 key
   - Model:例如 `deepseek-chat` / `deepseek-v3` / `qwen-plus`
6. 点**测试连接**,应返回成功
7. 点**保存**

> 此处保存的值写入 `system_configs` 表,进程重启/容器重建都不丢。`.env` 里的 `LLM_*` 仅是 DB 无配置时的兜底。

---

## 13. 日常运维

### 13.1 日志

```bash
cd ~/apps/doccheck

# 实时后端日志
docker compose logs -f --tail 100 backend

# 只看错误
docker compose logs backend 2>&1 | grep -Ei "error|exception|traceback"

# 前端 nginx 访问日志
docker compose exec frontend tail -f /var/log/nginx/access.log
```

日志自动滚动:`daemon.json` 已配 `max-size 20m / max-file 5`,每个容器日志上限 100 MB。

### 13.2 备份

**DB**:

```bash
mkdir -p ~/backups

docker compose exec -T db \
  pg_dump -U postgres documentcheck | gzip > \
  ~/backups/doccheck-db-$(date +%Y%m%d-%H%M%S).sql.gz
```

**uploads**(投标原文件):

```bash
sudo tar czf ~/backups/doccheck-uploads-$(date +%Y%m%d).tar.gz \
  -C /var/lib/docker/volumes/doccheck_uploads/_data .
```

**定时(crontab)**:

```bash
(crontab -l 2>/dev/null; cat <<'EOF'
# 每天 3:00 备份 DB,保留 30 天
0 3 * * * cd ~/apps/doccheck && docker compose exec -T db pg_dump -U postgres documentcheck | gzip > ~/backups/doccheck-db-$(date +\%Y\%m\%d).sql.gz && find ~/backups -name 'doccheck-db-*.sql.gz' -mtime +30 -delete

# 每周日 4:00 备份 uploads,保留 8 周
0 4 * * 0 sudo tar czf ~/backups/doccheck-uploads-$(date +\%Y\%m\%d).tar.gz -C /var/lib/docker/volumes/doccheck_uploads/_data . && find ~/backups -name 'doccheck-uploads-*.tar.gz' -mtime +56 -delete
EOF
) | crontab -

crontab -l
```

### 13.3 升级到新版本

```bash
cd ~/apps/doccheck

# 先备份(见 13.2)
docker compose exec -T db pg_dump -U postgres documentcheck | gzip > ~/backups/pre-upgrade-$(date +%Y%m%d).sql.gz

# 拉新代码
git fetch --tags
git checkout v0.3.0        # 换成新版本号

# 若有新 migration,先跑
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm backend alembic upgrade head

# 重建镜像 + 滚动重启
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 健康检查
docker compose ps
curl -sS https://doccheck.yourdomain.com/api/health
```

### 13.4 恢复

```bash
# DB
gunzip -c ~/backups/doccheck-db-20260422.sql.gz | \
  docker compose exec -T db psql -U postgres documentcheck

# uploads
sudo rm -rf /var/lib/docker/volumes/doccheck_uploads/_data/*
sudo tar xzf ~/backups/doccheck-uploads-20260422.tar.gz \
  -C /var/lib/docker/volumes/doccheck_uploads/_data
```

---

## 14. 常见问题

### 14.1 登录一直 401

- DB 里 `users` 表有无 admin?`docker compose exec db psql -U postgres documentcheck -c "SELECT username FROM users;"`
- 如无,重启 backend 触发 seed:`docker compose restart backend && docker compose logs backend | grep -i seed`

### 14.2 检测一直卡"等待 LLM..."

- 管理后台 → LLM 配置 → 点"测试连接"
- 失败的话看 backend 日志:`docker compose logs backend | grep -i llm`
- 常见原因:API Key 错、Base URL 拼错(例如末尾多了 `/`)、模型名不对

### 14.3 上传报 413 Request Entity Too Large

- 宿主 `/etc/nginx/conf.d/doccheck.conf` 里 `client_max_body_size 200m` 有没有?
- 容器内 `frontend/nginx.conf` 里也要有(默认 1m)

### 14.4 SSE 进度不刷新

- nginx 配置里 `proxy_buffering off` 必须有(宿主和容器两处都要)
- F12 Network 看 `/analysis/events` 是否 200 且连接不断

### 14.5 拉 docker 镜像超时

- 换 `daemon.json` 里 `registry-mirrors` 数组的顺序,或删掉不可用的项
- 重启 docker:`sudo systemctl restart docker`
- 实在不行用阿里云专属加速器(§3.4 末)

### 14.6 SELinux Enforcing 导致 docker volume 权限问题

症状:后端启动报 `PermissionError: [Errno 13] Permission denied: '/app/uploads'`

```bash
# 临时放行
sudo setenforce 0
# 永久放行
sudo sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config
```

或者更保守(只让 docker volume 绕开 SELinux):在 `docker-compose.prod.yml` 的 volumes 后加 `:z`:

```yaml
volumes:
  - uploads:/app/uploads:z
```

### 14.7 alembic upgrade 报 "Target database is not up to date"

说明迁移链不完整。排查:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm backend alembic current
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm backend alembic history | head -20
```

然后 `alembic upgrade head` 跑一次。

### 14.8 certbot 失败:`Connection refused`

- 域名 DNS 没解析到这台公网 IP?`dig +short doccheck.yourdomain.com`
- 防火墙 80 没开?`sudo firewall-cmd --list-services | grep http`
- nginx 没在跑?`sudo systemctl status nginx`

### 14.9 前端访问 502 Bad Gateway

- 容器跑着吗?`docker compose ps`
- 容器里 nginx 能通吗?`curl -sS http://127.0.0.1:5173/`
- 宿主 nginx 日志:`sudo tail -50 /var/log/nginx/error.log`

---

## 附录

### A. 镜像源 URL 速查

| 项 | URL |
|---|---|
| CentOS 7 vault yum | `https://mirrors.aliyun.com/repo/Centos-vault-7.9.2009.repo` |
| EPEL 7 | `https://mirrors.aliyun.com/repo/epel-7.repo` |
| Docker CE (CentOS) | `https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo` |
| Docker Hub 镜像 | daocloud / dockerproxy / nju / sjtug(见 §3.4) |
| pip (清华) | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| npm (淘宝) | `https://registry.npmmirror.com` |
| alpine apk (阿里) | `https://mirrors.aliyun.com/alpine/` |
| nginx yum (CentOS) | `https://mirrors.aliyun.com/nginx/centos/7/$basearch/` |
| Ubuntu apt | `https://mirrors.aliyun.com/ubuntu/` |
| Debian apt | `https://mirrors.aliyun.com/debian/` |

### B. 文件路径速查

| 内容 | 路径 |
|---|---|
| 代码 | `~/apps/doccheck` |
| 环境变量 | `~/apps/doccheck/.env` (600) |
| 生产 override | `~/apps/doccheck/docker-compose.prod.yml` |
| uploads 数据 | `/var/lib/docker/volumes/doccheck_uploads/_data` |
| pgdata 数据 | `/var/lib/docker/volumes/doccheck_pgdata/_data` |
| Docker daemon 配置 | `/etc/docker/daemon.json` |
| 宿主 nginx 站点 | `/etc/nginx/conf.d/doccheck.conf` |
| Let's Encrypt 证书 | `/etc/letsencrypt/live/<域名>/` |
| 备份 | `~/backups/` |

### C. 版本对应

| 组件 | 版本要求 |
|---|---|
| Docker | ≥ 24.0(本指南在 27.x 上验证) |
| docker compose plugin | ≥ 2.20 |
| Python(容器内) | 3.12 |
| Node(容器内) | 22 |
| PostgreSQL | 16-alpine |
| 仓库 tag | v0.2.0 |

### D. 一键启动脚本(可选)

如果后续要在新机器上重复部署,可以把 §7~§8 封装成脚本:

```bash
cat > ~/apps/doccheck/deploy.sh <<'EOF'
#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "缺少 .env 文件,请先按文档 §6 创建"
  exit 1
fi

echo "==> 构建镜像"
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

echo "==> 启动 DB 并等 healthy"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d db
until docker compose ps db | grep -q "(healthy)"; do sleep 2; done

echo "==> 跑 alembic 迁移"
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm backend alembic upgrade head

echo "==> 启动全部"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

echo "==> 健康检查"
sleep 5
docker compose ps
docker compose exec backend curl -sS http://127.0.0.1:8000/api/health
EOF

chmod +x ~/apps/doccheck/deploy.sh
```

之后升级就只需:

```bash
cd ~/apps/doccheck && git pull && ./deploy.sh
```

---

**完成标志**:`https://你的域名` 能访问 + 管理员登录 + LLM 测试通过 + 能跑完一次检测。达到后把 `.env`、`/etc/nginx/conf.d/doccheck.conf`、`/etc/docker/daemon.json` 备份到异地,避免服务器崩溃时无法快速重建。
