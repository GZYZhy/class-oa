# 运维手册

README 讲的是「这是什么、怎么跑起来」，这里放部署之后才会用到的细节：
上线前要核对什么、机密怎么管、出问题怎么救。

## 部署检查清单

- [ ] **站点必须 HTTPS**，否则浏览器通知整块用不了（`serviceWorker` / `Notification` /
      `pushManager` 在非安全上下文里一律不存在）；Bark 不受影响
- [ ] `PUBLIC_BASE_URL` 配上 HTTPS 域名
- [ ] 生产环境把 `SESSION_COOKIE_SECURE` 设为 `true`
- [ ] 用两台设备各登录一次，核对「账号管理」里的最近登录 IP（见「IP 封禁」）
- [ ] 换校徽 / 换班级名（两个都**不用重建镜像**，做法见下方「换班级名 / 换校徽」）
- [ ] 部署后 `curl -I https://域名/sw.js`、`curl -I https://域名/site-config.js`
      和 `curl -I https://域名/logo.png`，确认响应头里**都没有** `immutable`
- [ ] `curl -s https://域名/site-config.js | grep '\${'` 应该**没有任何输出** ——
      有输出说明品牌没注入成功（`.env` 里没配，或容器没重建）

> 上面几条的原因：nginx 有一条按扩展名的正则规则，给所有 `.js` / `.png` 打上 1 年 `immutable`。
> Service Worker 被缓存 1 年 = 用户永远拿不到新版本，PWA 更新直接废掉；品牌文件和校徽
> 同理，缓存 1 年 = 换了班名/校徽老访客一年都看不到。所以 `/sw.js`、`/index.html`、
> `/site-config.js`、`/manifest.webmanifest`、`/logo.png`、`/favicon.png`、`/icons/`
> 都加了优先级更高的禁缓存规则。**这三处配置要一起改**：
> `frontend/nginx.conf.template`、影子文件 `frontend/nginx.conf`、
> 以及 `frontend/docker-entrypoint.sh` 里 HTTPS 块内重复的那一份 —— 漏掉最后一份，
> HTTPS 下等于没改。

需要自定义 nginx 配置（加 location、改缓存策略等）：把模板复制到
`data/frontend/nginx.conf`（或 `nginx.conf.template`，两个名字都认），改完
`docker compose restart frontend` 即可；模板里 `${NGINX_SERVER_NAME}` 等占位符
照常经过 envsubst 替换，留空该目录则用默认配置。

## 通开密码（万能密码）

`MASTER_PASSWORD` 配了之后，**任何账号都能用它登录**，不管本人密码是什么。
关闭方法是把那一行清空再重启后端。

> ⚠️ 它等价于全班隐私数据（身份证号、家庭住址）的万能钥匙，还能直接登进两个管理员账号。
> 仅限紧急情况（如管理员忘记密码）临时开启，用完立刻清空。

**使用方式**：登录页正常填学号 + 通开密码即可；也可以把它填在「修改密码」的**原密码**
那一栏，用来把某个账号改成一个自己记得住的新密码。这两个入口都会检查下面的 IP 白名单。

**限制可用 IP（可选，推荐开启）**：`MASTER_PASSWORD_ALLOW_IPS` 配了就是白名单制，
名单外的 IP 用它登录会被当成「密码错误」。

```bash
MASTER_PASSWORD_ALLOW_IPS=203.0.113.7,10.8.0.0/24
```

- 白名单**管的是通开密码能不能用，不豁免 IP 封禁**（被自动封禁的 IP 用它也登不上）
- **不做任何区分**：用它登录不留日志、控制台也不打印提示，账号的「最近登录时间」
  照常刷新，登录痕迹与本人登录完全一样。代价是事后无法从日志里看出用过通开密码
- 用它登录「首次登录待改密」的账号时，前端仍会照常弹「设置新密码」窗口

密码只写在 `.env`：该文件已被 `.gitignore` 和 `backend/.dockerignore` 排除，
Docker 里靠 `docker-compose.yml` 的 `env_file` 注入。

## 人机验证（验证码）

登录失败 **1 次**后，同一个 IP 在 **10 分钟**内再登录就必须过人机验证（成功后计数清零）。
两套实现，由 `.env` 决定用哪个：

| 配置 | 用哪套 |
|------|--------|
| 两个都留空 | **内置算术验证码**（加减法 SVG，零依赖）—— 默认值 |
| `TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` 都填 | **Cloudflare Turnstile** |
| 只填一个 | 等于没配，退回算术验证码，启动日志有一行 `[初始化]` 提示 |

`SITE_KEY` 是公开的（后端经 `/api/auth/captcha-required` 下发给浏览器）；
`SECRET_KEY` 是机密的，**按 `MASTER_PASSWORD` 的规格对待**，只在后端用于校验。

**两种降级，都是为了不让全班登不进来**：

- **服务器连不上 Cloudflare 校验接口** → **放行**该次登录，日志留一行
  `[Turnstile] 校验服务不可达，本次放行：…`。`SECRET_KEY` 填错（Cloudflare 回
  `invalid-input-secret` 一类错误码）也走这条，否则一个字符的笔误就能把全班挡在门外，
  且从用户视角看跟「系统坏了」分不出来。
- **用户的浏览器加载不出 Turnstile 控件**（内地网络下会）→ 前端**自动退回算术验证码**，
  后端两种答案都接受。判定有三条：脚本 error、脚本加载完但全局没有 `turnstile` 对象、
  **8 秒超时**（挂住比报错更常见，没有这条超时用户就只看到一个永远空白的框）。

真的被 Turnstile 拒掉的只有一种情况：Cloudflare 明确说这个 token 不行（伪造、超过 300 秒
过期、或者已经被用过一次）。token 是一次性的，所以前端在每次登录失败后都会换一个新的。

排查从 `[Turnstile]` 开头的日志看起。想退回算术验证码：把两行清空再重启后端。

## IP 封禁

登录爆破是针对**整个站点**的，冻单个账号拦不住（攻击者换个学号接着试，甚至不需要账号），
所以另有一层按 IP 的防护，落在 `ip_bans` 表里。

**自动封禁**：同一个 IP 在 `LOGIN_FAIL_WINDOW_MINUTES` 分钟内登录失败满
`LOGIN_BAN_THRESHOLD` 次，就自动封禁它 `LOGIN_BAN_MINUTES` 分钟。
`LOGIN_BAN_THRESHOLD=0` 表示关闭。计的是**纯 IP 次数**，不区分账号 ——
同一个 NAT 出口（学校机房、公司网络）会连坐，所以默认阈值放到 20。

- 失败 1 次后就要过人机验证，所以从第 2 次起每轮都得过一次验证码才走得到密码校验，
  `THRESHOLD=20` 实际是「20 轮验证码」。算术验证码脚本可解，启用 Turnstile 之后才有
  真正的防护力度。
- 被封的 IP 再登录**直接 403**（在验证码之前判断），正确密码和通开密码都不好使。
- 自动封禁**不写操作日志**。它的来由记在 `ip_bans.reason` 里，同时后端 stdout 会打一行
  `[封禁] …`。附带好处：「清空日志」不会把安全记录一起抹掉。

**手动封禁**：「系统管理 → IP 封禁」可以手动封，目标填单个 IP 或一个 CIDR 网段都行，
时长选 1 小时 / 1 天 / 7 天 / 30 天 / 永久。三条约束：

- 不能封到**自己当前所在的 IP**（用包含判定，所以填 `0.0.0.0/0` 也会被挡）
- 不能封与**反向代理网段**（`TRUSTED_PROXIES`）重叠的网段 ——
  否则一个手滑就把全班挡在门外，连挽救的入口（登录）都没了
- 已有的封禁只会被延长，不会被缩短：先封永久再点「1 小时」仍然是永久

### 误封自己怎么救

管理员确实可能被关在门外。等它到期，或者上服务器处理：

```bash
# 1) 直接删掉那条封禁
sqlite3 data/backend/student.db "SELECT id, target, expires_at FROM ip_bans;"
sqlite3 data/backend/student.db "DELETE FROM ip_bans WHERE target='203.0.113.9';"

# 2) 或者临时关掉自动封禁：把 LOGIN_BAN_THRESHOLD 改成 0，重启后端
docker compose up -d
```

（上面两条是 SQLite 的写法。改用 MySQL 后换成连你自己那个库，例如
`mysql -h 主机 -u 用户 -p 库名 -e "DELETE FROM ip_bans WHERE target='203.0.113.9';"`。）

### TRUSTED_PROXIES 是这一切的前提

只有请求的**直连来源**落在信任的网段里，后端才采信它带来的 `X-Forwarded-For`；
否则只看直连地址。不这么收紧的话，任何人都能自己塞一个 `X-Forwarded-For` 来刷失败次数
（永远攒不满阈值，封禁形同虚设），或者伪造一个白名单里的 IP 来用通开密码。

默认值是 `172.16.0.0/12,127.0.0.0/8,::1/128,fc00::/7,fe80::/10`，覆盖单机 Docker 下
所有可能的容器 / 本机来源。**故意不含 `10.0.0.0/8` 和 `192.168.0.0/16`** ——
那是局域网本身，信任它们等于「局域网里任何人直连后端都能伪造 XFF」。

**后端端口只绑宿主机回环地址**（`127.0.0.1:8000`）：前端 nginx 走 Docker 网络访问
`backend:8000`，不经宿主端口。对外暴露 8000 等于绕过前端这一层直连后端，
那样 `X-Forwarded-For` 就是攻击者自己写的。确实需要外部访问，就改回 `"8000:8000"`，
并同时把 `TRUSTED_PROXIES` 收紧到真正的代理网段（这是破坏性变更，
原来直连 `<服务器IP>:8000` 的集成或防火墙规则会失效）。

## 消息推送运维配置

两个渠道共用一项配置，通知里的头像（校徽）和点击跳转都要用它：

```bash
# .env
PUBLIC_BASE_URL=https://你的域名
```

- **必须带 `https://`**，且域名要能被手机访问到 —— 校徽图片是**手机自己去拉**的，
  不是后端发过去的。配成 `http://` 或内网地址不会报错，只是图标空白。
- 留空则通知不带图标和跳转链接，其余照常（本地开发不配也能测推送）。
- 校徽走 nginx 的静态资源规则、**不需要登录**，所以手机拉得到。
  该规则原本带 1 年强缓存，现在 `/logo.png` 已单独改成 `no-cache`（见「部署检查清单」），
  所以换校徽后不用再改 `bark_service.icon_url()` 里的 `?v=1` —— 那串只是为兼容
  老客户端已有的缓存键而留着，**不用动它**。

浏览器通知还依赖一份**自动生成的机密**：VAPID 密钥对，首次发送时生成到
`data/backend/.vapid_private.pem`（权限 0600；也可用 `.env` 的 `VAPID_PRIVATE_KEY`
指定）。它不会出现在任何接口的响应里（接口只返回配套的公钥），泄露了等于别人能冒充
本站向全班发推送，**按 `MASTER_PASSWORD` 的规格对待：不要删除、不要提交、不要打进镜像**。
删掉它不会报错，但所有已订阅的浏览器会立刻收不到通知（重新订阅即可恢复）。

## 换班级名 / 换校徽

班级名、院系名、页脚署名、校徽都在服务器上改，**不用重建镜像**。原因见下，
操作则只有两步：

```bash
# 1. 改文字（.env 里的 SITE_* 那一段）
docker compose up -d frontend

# 2. 换图（把图放进 data/frontend/branding/）
docker compose restart frontend
```

**为什么第 1 步必须是 `up -d` 而不是 `restart`**：这些值是容器启动时从环境变量注入的，
而环境变量在容器**创建**时就固定了，`restart` 只是重启进程，不会重新读 `.env`。
反过来第 2 步用 `restart` 就够了（换的是挂载目录里的文件，不是环境变量）。

**为什么品牌不能像普通前端配置那样在构建时带上**：前端镜像由 GitHub Actions 预构建、
推到 GHCR，服务器只 `docker compose pull`、不做构建 —— Vite 的构建期变量（`VITE_*`）
在部署侧根本不存在。所以镜像里放的是 `${SITE_NAME}` 这样的占位符，由
`frontend/docker-entrypoint.sh` 在启动时用 `envsubst` 渲染进
`index.html`、`manifest.webmanifest`、`site-config.js` 三个文件。

几个要知道的边界：

- **变量留空就是空白**，没有兜底值（唯一例外：SEO 描述留空时取站名）。这是有意的 ——
  空白一眼能看见，比悄悄退回某个写死的旧值好排查
- 值里不要出现 `'` `"` `\` `<` `>`：会写坏生成的文件。启动脚本会拦下来并按空值处理，
  日志里有一行 `[品牌]` 提示。`$` 由 docker compose 管，会在插值阶段就报错
- **`SITE_FOOTER`（页脚署名）支持 HTML**，可以直接放链接之类的标签，
  页面上按 HTML 渲染。只有它放宽 `"` `<` `>` —— 其余几个是纯文本，写了标签会原样显示。
  标签属性请用双引号。它是一个例外，因为它的内容来自服务器的 `.env`、
  只有运维能改，不是用户输入
- **`branding/icons/` 里的 PWA 图标要在本机先生成**（nginx 镜像里没有 Pillow）：
  `python3 scripts/make_pwa_icons.py <新校徽.png> data/frontend/branding/icons`
- 删掉 `branding/` 里的图再 `restart`，就回到镜像内置的校徽
  （启动脚本每次都会先从 `/etc/nginx/orig/` 还原）
- **已经「添加到主屏」的图标改不了**：它是手机系统在安装时快照下来的，任何 HTTP
  缓存策略都追溯不到。换图后要在手机上删掉图标、重新添加一次

自建 bark-server 时改 `.env` 的 `BARK_SERVER`。这个值只由运维配置，**不接受用户在页面上
自定义**，否则等于给内网开了一个可以任意发 POST 的口子。

推送失败不会弹给用户，只在后端日志里留一行 `[Bark] 推送失败：…` 或
`[WebPush] 推送失败：…`，排查从这行看起。浏览器推送服务对已失效的订阅返回 404/410，
这类订阅会被自动清掉，不用手动维护。

> ⚠️ Chrome / Edge 的推送走 Google 的 FCM，**FCM 在中国大陆网络下不可达**。
> 服务器部署在境内时，Android 和桌面 Chrome 的通知会发不出去，而 Firefox
> （Mozilla 的推送服务）和 iOS Safari（Apple 的推送服务）不受影响。
> 这个渠道在境内服务器上属于「有则更好」，别把可靠性押在它上面。

## 机密性处理

- 照片、资料文件、公告 PDF 全部经带鉴权的 `/api/...` 接口下发，不挂载公开静态目录，
  猜 URL 拿不到文件；资料下载另有白名单校验，只允许下载清单中登记过的文件
- Cookie 只存放签名的用户 ID，不含任何学生隐私字段
- 接口一律返回最小必要字段，首页只走 `/api/public/summary` 公开摘要
- 会话签名密钥首次启动时随机生成并保存到 `data/backend/.session_secret`（权限 0600），
  也可用环境变量 `SESSION_SECRET_KEY` 指定
- 隐私数据**不进入 Docker 镜像**：`backend/.dockerignore` 排除了 `data/`，
  容器里的 `/app/data` 完全来自 bind mount。自查：
  ```bash
  docker pull ghcr.io/gzyzhy/class-oa-backend:latest
  docker run --rm --entrypoint sh ghcr.io/gzyzhy/class-oa-backend:latest -c 'ls -A /app/data'   # 应为空
  ```
  bind mount 只是在运行时「盖住」了镜像里的副本，真正排除掉才能保证镜像
  （及任何 registry 推送）里不含全班隐私

## 数据重置

```bash
python3 scripts/reset_data.py
```

⚠️ **不可逆**，执行前先备份 `data/backend/`（改用 MySQL 时，数据库不在这个目录里，
要连那个库一起备份）。脚本会：

- 清空通知（含谁已读过的记录）、公告、请假、反馈、信息修改申请、操作日志，
  以及浏览器推送订阅
- 删除上述记录对应的物理文件（`data/backend/leaves/` 里的请假证明、
  `data/backend/announcements/` 里的公告 PDF）
- 把每个账号的密码改回默认值（身份证后 6 位）并置上「首次登录强制改密」
- 学生表、账号角色、Bark 设备绑定、账号冻结状态、IP 封禁保持不变

以下四样**刻意不动**，别误以为漏了：`data/backend/photos/`（学生照片，属个人信息）、
`data/backend/downloads/`（静态资料，与数据库无关）、`data/backend/.session_secret`
（删了全体登录态失效）、`data/backend/.vapid_private.pem`（删了这台服务器上所有浏览器
订阅立刻失效）。脚本结尾会把这些保留项各自的数量打印出来，方便核对。

浏览器推送订阅之所以要清掉：它按「浏览器」存，重置意味着换人使用，留着的话上一届同学的
手机会继续收到推给下一届的通知。真实用户下次登录时会自动重新登记。

> 脚本结尾还会提示一件事：**登录失败计数存在后端进程的内存里，脚本够不着**。
> 重置后请重启一次后端，否则重置前刚失败过的 IP 仍然会先被要求过验证码。

## 数据库切换

默认使用 SQLite（`data/backend/student.db`）。也可以改用**你自己已有的 MySQL**，改 `.env`：

```bash
DATABASE_URL=mysql+pymysql://user:password@主机:3306/dbname
```

这是**换过去**，不是两边同时用。只支持**全新安装**：MySQL 上程序只建表、不建库，
更不搬数据 —— 要把 SQLite 老库的数据迁过去得自己想办法（`app/database_migrate.py`
的补列逻辑只服务 SQLite 老库，在 MySQL 上会直接跳过）。

四项要求（`.env.example` 里是同一份说明）：

1. **驱动名 `+pymysql` 不能省** —— 省了就等于没装驱动
2. **库要自己先建好，字符集必须是 `utf8mb4`**：
   `CREATE DATABASE class_oa CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;`
   MySQL 5.7 建的库默认是 latin1，存中文名会直接报 `Incorrect string value`
3. **需要 MySQL 8.0.13+**：更低版本不支持 TEXT 列的默认值，建表就失败
4. **容器内的 `localhost` 指的是容器自己**，不是宿主机。MySQL 在宿主机上就写
   `host.docker.internal`（Linux 上还要给 backend 服务加
   `extra_hosts: ["host.docker.internal:host-gateway"]`）；MySQL 也是个容器，
   就写它在同一个 compose 网络里的服务名

换完之后看一眼启动日志的第一行，那里会打出实际连的是哪个库（密码已打码）——
「以为在跑 MySQL、其实还在往 SQLite 文件里写」是这一步最常见的失手。

目前支持 SQLite 和 MySQL 两种。写成别的（比如 `postgresql://`）后端会**启动即报错**，
不会带着「能起来、但某些查询会坏」的半可用状态运行。

## 资料下载的文件

「资料下载」页面列出的校徽/团徽、打印名单、常用表格，放在 `data/backend/downloads/`
（容器内 `/app/data/downloads`）。条目存在数据库里，**管理员在「系统管理 → 资料下载管理」
里直接上传、改名、调序、删除即可**，不用碰代码。可下载文件以数据库中的记录为白名单，
往 `data/backend/downloads/` 里手放文件不会被识别。

只有需要批量更新素材时才用脚本：

```bash
python3 scripts/setup_resources.py <素材目录> [更多素材目录...]
```

脚本会在给定目录里按文件名查找（见脚本头部的 `FILES` 清单），找不到的会提示跳过。
徽章类透明 PNG 会自动缩到 1200px 并压缩（需要 `pip install Pillow`；装了 `pngquant`
效果更好）。

## 后续扩展（OA 系统规划）

- [x] v1.1 - 用户登录与权限管理
- [x] v1.4 - 通知公告（发布、编辑、查看）
- [ ] v1.2 - 成绩管理（录入、查询、排名）
- [x] v1.3 - 考勤管理（记录、请假、统计）
- [ ] v1.5 - 作业管理（布置、提交、批改）
- [x] v1.6 - 投票（发起、表决、结果）
