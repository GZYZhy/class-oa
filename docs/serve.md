# 部署与运维

从一台空服务器到可用的班级站点，以及上线之后的升级、备份、排错与安全事项。
日常操作说明见 [使用手册](guide.md)。

![架构](images/architecture.svg)

## 1. 运行要求

| 项 | 要求 |
|---|---|
| 系统 | Linux（x86_64 / arm64 均可） |
| Docker | 24 以上，含 Compose v2（`docker compose`） |
| 资源 | 1 核 1 GB 即可起步；磁盘按照片与附件量预留，建议 ≥ 5 GB |
| 网络 | 能访问 `ghcr.io` 拉取镜像；对外提供 HTTPS |
| 时区 | 容器内固定 `Asia/Shanghai` |

镜像托管在 GitHub Container Registry，**已公开**，无需登录即可拉取：

```
ghcr.io/gzyzhy/class-oa-backend:latest
ghcr.io/gzyzhy/class-oa-frontend:latest
```

前端与后端是两个镜像；每次发布同时提供 `latest` 与语义版本标签（如 `1.13.2`），
线上默认跟随 `latest`。

## 2. 目录结构

服务器上只需要两个文件，不需要源码和构建链：

```
class-oa/
├── docker-compose.yml
├── .env                 # 配置与机密，不提交、不进镜像
└── data/
    ├── backend/         # 数据库、照片、资料、附件、密钥
    └── frontend/        # 可选的自定义 nginx 配置
```

`data/` 会在容器启动时自动创建。**它是唯一的持久化位置**：换镜像、重建容器都不会动它，
备份与迁移也只需要打包这个目录。

## 3. 五分钟部署

### 3.1 取文件

```bash
git clone https://github.com/GZYZhy/class-oa.git
cd class-oa
```

也可以只下载仓库里的 `docker-compose.yml` 与 `.env.example`。

### 3.2 写配置

```bash
cp .env.example .env
```

最少先填这几项：

```bash
SITE_NAME=某班信息管理系统
SITE_SHORT_NAME=某班
PUBLIC_BASE_URL=https://oa.example.com
SESSION_COOKIE_SECURE=true
BOOTSTRAP_PASSWORD=<一串足够长的随机字符>
```

其余（SMTP、Turnstile、推送、封禁阈值等）可以等站点跑起来后再补。
完整清单和逐项说明见仓库里的 `.env.example`。

> `SITE_*` 里的 `' " \ < >` 会写坏生成的文件，启动脚本会拦下并按空值处理；
> `$` 会被 compose 当成插值，需要写成 `$$`。

### 3.3 启动

```bash
docker compose up -d
docker compose ps
curl -s http://127.0.0.1:8000/api/health
```

健康检查应返回：

```json
{"status":"ok","app":"班级信息管理系统","version":"1.13.2"}
```

`version` 是当前实际运行的版本号，排查「以为更新了其实没更新」时先看它。

### 3.4 首次初始化

空库启动时系统里一个账号都没有。配置了 `BOOTSTRAP_PASSWORD` 后，后端会临时准备一个
`admin` 账号，用它登录会强制进入初始化引导：

1. 用 `admin` + `BOOTSTRAP_PASSWORD` 登录；
2. 导入学生 Excel，或手工新增一名学生；
3. 从名单里指定一名管理员，点「完成初始化」；
4. 临时账号当场删除，用刚指定的管理员登录（初始密码是身份证号后 6 位，
   没有则学号后 6 位，首次登录必须改密）。

完成后建议把 `.env` 里的 `BOOTSTRAP_PASSWORD` 清空并重启：

```bash
docker compose up -d backend
```

**不配 `BOOTSTRAP_PASSWORD` 时这个功能整个关闭**——空库谁也登不进去。
它不是可选项，是首次部署的必做一步。

## 4. 反向代理与 HTTPS

前端容器在宿主机上监听 `8080`，后端只绑定 `127.0.0.1:8000`。
建议由宿主机上的 nginx 终止 HTTPS 再转发到 `8080`：

```nginx
server {
    listen 443 ssl http2;
    server_name oa.example.com;

    ssl_certificate     /path/fullchain.pem;
    ssl_certificate_key /path/privkey.pem;

    client_max_body_size 70m;     # 与容器默认上传上限一致

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;   # 大附件与导出文件
    }
}
```

> 宿主机 nginx 因环境而异（宝塔、1Panel、手写配置），这里只是一份通用示例。

### 4.1 TRUSTED_PROXIES 必须配对

后端只信任 `TRUSTED_PROXIES` 网段带来的 `X-Forwarded-For`。默认值覆盖 Docker 与本机来源。
如果反向代理与后端不在同一台机器上，或 Docker 使用了 `10.x` 自定义地址池，
要把代理的真实网段加进去，否则所有请求会被当成同一个 IP：

- 自动封禁会把全班当成同一个人；
- 登录记录里的来源 IP 全部相同；
- 通开密码的白名单按错误地址判断。

上线后请用两台设备各登录一次，在「系统管理 → 账号管理」里核对最近登录 IP 是否不同。

### 4.2 缓存

**不要在前端做整站缓存。** 登录页、接口响应、`/api/auth/me` 一旦被代理或面板缓存，
浏览器 A 会拿到浏览器 B 的会话，表现是「全班像同一个人登录」。

- 宝塔面板的「全局缓存」最容易踩：关掉它，或至少排除 `/api/`；
- 静态资源（带 hash 的文件）可以长缓存；
- `/sw.js`、`/index.html`、`/site-config.js`、`/manifest.webmanifest` 必须 `no-cache`。
  镜像内置的 nginx 配置已经处理，若在宿主机再加一层缓存，请同样排除这几个路径。

## 5. 环境变量

完整说明见 [`.env.example`](../.env.example)。常用的：

| 变量 | 作用 |
|---|---|
| `SITE_NAME` / `SITE_SHORT_NAME` / `SITE_SUBTITLE` / `SITE_COLLEGE` / `SITE_MAJOR` / `SITE_FOOTER` | 站点品牌，容器启动时注入 |
| `PUBLIC_BASE_URL` | 对外 HTTPS 地址，推送里的图标与跳转要用 |
| `SESSION_COOKIE_SECURE` | 生产环境设为 `true` |
| `TRUSTED_PROXIES` | 信任的反向代理网段，**部署前核对** |
| `BOOTSTRAP_PASSWORD` | 首次初始化口令，用完清空 |
| `MASTER_PASSWORD` | 通开密码，仅应急开启；可用 `MASTER_PASSWORD_ALLOW_IPS` 限制来源 |
| `TWO_FACTOR_MASTER_CODE` | 二次验证万能码，6 位数字，仅登录第二因素生效 |
| `LOGIN_BAN_THRESHOLD` / `_MINUTES` / `LOGIN_FAIL_WINDOW_MINUTES` | 登录失败封禁 |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_SECURITY` | 邮件通知与邮箱验证码 |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile 人机验证 |
| `HEAD_INJECT` | 原样插入每页 `<head>`，放统计或第三方脚本 |
| `DATABASE_URL` | 默认 SQLite；也可指向 MySQL |
| `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | 浏览器推送签名 |
| `BARK_SERVER` | Bark 推送服务地址 |

品牌变量改完后必须**重建前端容器**才生效：

```bash
docker compose up -d frontend     # 不是 restart
```

换校徽或主屏图标：把图放进 `data/frontend/branding/`，再 `docker compose restart frontend`。
PWA 图标先用 `python3 scripts/make_pwa_icons.py <新校徽.png> data/frontend/branding/icons` 生成。
已经「添加到主屏」的图标由手机快照，需要删掉重加。

## 6. 升级与回滚

![发布流程](images/deploy-flow.svg)

推送 `vX.Y.Z` 标签后，GitHub Actions 先跑前后端全量测试，全部通过才构建并推送镜像
（同时带 `latest`、日期、提交和同名的语义版本标签）。普通提交只跑测试，不出镜像，
`latest` 也不会被未发版的提交覆盖。服务器上：

```bash
docker compose pull
docker compose up -d
curl -s http://127.0.0.1:8000/api/health
```

只执行 `up -d` 不会去 registry 检查新版本，**必须带 `pull`**。

升级前先备份 `data/`（见下一节）。需要回滚时，把版本标签写进 `.env`：

```bash
IMAGE_TAG=1.13.2
```

再 `docker compose up -d`。数据卷原地保留，不会被旧镜像改动。

## 7. 备份与恢复

### 7.1 SQLite（默认）

```bash
# 先停后端，保证 SQLite 与文件处于一致状态
docker compose stop backend
tar czf class-oa-data-$(date +%F).tgz data
docker compose start backend
```

恢复：

```bash
docker compose down
rm -rf data
tar xzf class-oa-data-YYYY-MM-DD.tgz
docker compose up -d
```

`data/backend/` 里有：`student.db`、学生照片、资料文件、公告附件、请假证明、
会话签名密钥、VAPID 私钥。**`.session_secret` 与 `.vapid_private.pem` 属于机密**，
备份包不要公开分享，恢复时保持文件权限。

### 7.2 MySQL

`DATABASE_URL` 指向 MySQL 时，数据库**不在** `data/` 里，要单独备份；`data/` 仍要备份
（照片、附件、密钥都在里面）。

## 8. 安全

### 8.1 必做项

- 站点使用 HTTPS；生产环境 `SESSION_COOKIE_SECURE=true`。
- 核对 `TRUSTED_PROXIES`，避免全员被当成同一个 IP。
- 首次初始化完成后清空 `BOOTSTRAP_PASSWORD`。

### 8.2 应急入口

**通开密码 `MASTER_PASSWORD`**：任何账号都能用它登录。仅限紧急情况临时开启，
建议同时配置 `MASTER_PASSWORD_ALLOW_IPS` 白名单。它不豁免 IP 封禁。

**二次验证万能码 `TWO_FACTOR_MASTER_CODE`**：登录时输入这串 6 位数字，可顶替邮箱验证码
或身份验证器。必须恰好 6 位数字，否则视为未配置。命中后的表现与真实验证码完全一致
（不写额外日志、响应无额外字段），用完请清空并重启后端。

两者都属于「全班隐私的万能钥匙」，**不要在 `.env` 里长期保留**。

### 8.3 登录防护

- 登录失败 1 次后要求人机验证；同 IP 失败达到阈值自动封禁。
- 支持通行密钥（设备指纹 / 面容 / Windows Hello）与可选二次验证
  （邮箱验证码 / TOTP / 一次性恢复码）。
- 含名单与审批记录的页面盖有「姓名@班级 日期」水印，便于截图溯源。

### 8.4 隐私

- 照片、资料、公告附件全部经鉴权接口下发，不挂公开静态目录。
- 隐私数据不进入镜像：构建时排除 `data/`，运行时用数据卷挂载。
- 数据库与密钥只存在 `data/backend/`，备份与迁移时注意保管。

## 9. 通知渠道

| 渠道 | 需要的配置 |
|---|---|
| 站内信 | 无，开箱即用，唯一必达 |
| 邮件 | `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_SECURITY` |
| Bark | 用户在页面上填设备 ID；`BARK_SERVER` 可改自建服务 |
| 浏览器推送 | `PUBLIC_BASE_URL` + VAPID 私钥（首次自动生成） |
| Webhook | 用户自己填地址，无服务端配置 |

`PUBLIC_BASE_URL` 必须带 `https://` 且手机能访问到，否则推送没有图标和跳转。
Chrome / Edge 的推送走 Google 服务，**境内网络下可能不可达**，建议把 Bark 作为主要渠道。

## 10. 多实例（多个班级）

同一组镜像可以服务多个班级，每个实例一份目录、一份 `.env`、一份数据卷：

```bash
cp -r class-oa class-oa-2
cd class-oa-2
# 改 docker-compose.yml 的 name、container_name、端口
# 改 .env 的 SITE_*、PUBLIC_BASE_URL、BOOTSTRAP_PASSWORD
docker compose up -d
```

三处必须不同：Compose 项目名、宿主端口、`data/` 目录。镜像与版本可以共用。
会话密钥与 VAPID 私钥会在各自的数据目录里**独立生成**，不要互相复制。

## 11. 数据库切换（MySQL）

```bash
DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname
```

- 驱动名 `+pymysql` 不能省；
- 库要自己建，字符集必须是 `utf8mb4`；
- 需要 MySQL 8.0.13+；
- 容器内的 `localhost` 指容器自己，宿主机要写 `host.docker.internal`（Linux 需加
  `extra_hosts: ["host.docker.internal:host-gateway"]`），MySQL 也是容器就写服务名。

只支持全新安装，不自动搬数据。切换后看启动日志第一行，确认实际连的是哪个库。

## 12. 故障排查

**页面 502**
后端没起来或健康检查未通过：

```bash
docker compose ps
docker compose logs --tail=100 backend
curl -s http://127.0.0.1:8000/api/health
```

**更新后版本没变**
`up -d` 不会自动拉新镜像；先 `docker compose pull`，再看 `/api/health` 的 `version`。

**拉镜像超时或 401**
GHCR 在部分网络下会超时，重试即可：

```bash
for i in 1 2 3 4 5; do docker compose pull && break; sleep 5; done
```

镜像已公开，正常情况下不需要 `docker login`。

**全班像是同一个人登录 / 反复被踢**
先查代理缓存（见 4.2），再看 `TRUSTED_PROXIES`。无 Cookie 访问 `/api/auth/me`
应当返回 401；如果返回 200，说明响应被缓存了。

**上传大附件失败**
宿主机 nginx 与容器内的 `client_max_body_size` 都要够大（默认 70M）。
超时类错误同时检查 `proxy_read_timeout`。

**时间不对**
容器已固定 `TZ=Asia/Shanghai`；宿主机与反向代理也应是同一时区。

**忘记管理员密码**
用 `MASTER_PASSWORD` 登录后到「账号管理」重置；用完后清空并重启。

**数据目录权限错误**
容器内通常以 root 运行，`data/` 属主为 root 属正常；若手工改过属主导致无法写入，
恢复为可读写并重启。

## 13. 数据重置

把系统退回「刚导入完名单」的状态（毕业交接、换届时用）：

```bash
python3 scripts/reset_data.py
```

需要仓库源码与 Python 环境。**不可逆**，执行前先备份 `data/`。
脚本保留学生、账号角色、Bark 绑定、冻结状态与 IP 封禁；清空通知、办件、日志、
推送订阅，并把密码重置为初始值。执行后重启后端，清掉内存里的登录失败计数。

## 14. 从源码构建（可选）

正常部署不需要构建。确实要自己出镜像时：

```bash
./scripts/build_images.sh --push
```

需要本机 Docker 与已登录的 GHCR 账号。构建完成后服务器照常 `pull` 即可。
