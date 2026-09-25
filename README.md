# 班级信息管理系统

一个面向班级的学生信息管理系统，支持分类查询、统计检索，后续可扩展为小型 OA 系统。

## 功能特性

- 📊 **数据总览** - 关键指标一目了然，多维度图表展示
- 👥 **学生信息** - 完整的学生信息列表，支持多条件筛选搜索、排序，内置**点名**功能
- 📈 **分类统计** - 性别、民族、政治面貌、宿舍、贫困生、高考分数段等多维统计
- 🔍 **灵活筛选** - 支持关键词搜索、性别/民族/政治面貌/宿舍/贫困生等分类筛选
- 🔔 **消息推送** - 办件状态变化、新通知公告、有待自己审核的办件时推到手机或电脑，
  两个渠道任选或都开：**浏览器通知**（不用装东西）和 **Bark**（iOS 更省电，可选）
- 📲 **PWA** - 可「添加到主屏」当独立应用用；iOS 上这也是收浏览器通知的前置条件
- 📱 **响应式界面** - 基于 Element Plus 的现代化 UI

## 技术栈

### 后端
- **Python 3.12** - 开发语言
- **FastAPI** - 高性能 Web 框架
- **SQLAlchemy 2.0** - ORM 框架
- **SQLite** - 数据库（可平滑升级为 PostgreSQL/MySQL）
- **Pydantic** - 数据验证

### 前端
- **Vue 3** - 前端框架
- **Element Plus** - UI 组件库
- **ECharts** - 图表库
- **Pinia** - 状态管理
- **Vue Router** - 路由管理
- **Axios** - HTTP 客户端
- **Vite** - 构建工具

### 部署
- **Docker** - 容器化部署
- **Nginx** - 前端静态服务 & 反向代理
- **docker-compose** - 服务编排

## 项目结构

```
oa/
├── backend/                # 后端服务
│   ├── app/
│   │   ├── api/           # API 路由
│   │   ├── models/        # 数据模型
│   │   ├── schemas/       # Pydantic 模式
│   │   ├── services/      # 业务逻辑
│   │   ├── config.py      # 配置
│   │   ├── database.py    # 数据库连接
│   │   ├── database_migrate.py  # 启动时给老库补列（create_all 只建新表）
│   │   └── main.py        # 应用入口
│   ├── requirements.txt   # Python 依赖
│   └── Dockerfile         # 后端 Dockerfile
├── frontend/              # 前端服务
│   ├── src/
│   │   ├── api/           # API 接口
│   │   ├── components/    # 组件
│   │   ├── router/        # 路由
│   │   ├── store/         # 状态管理
│   │   ├── styles/        # 样式
│   │   ├── utils/         # 工具函数
│   │   ├── views/         # 页面
│   │   ├── App.vue
│   │   └── main.js
│   ├── public/
│   │   ├── sw.js           # Service Worker（只处理推送，不做离线缓存）
│   │   ├── manifest.webmanifest
│   │   └── icons/          # PWA 图标（由 scripts/make_pwa_icons.py 生成）
│   ├── nginx.conf         # Nginx 配置（本地直跑用；容器用 nginx.conf.template）
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile         # 前端 Dockerfile
├── data/                  # 运行时数据（不提交，统一放这里方便备份迁移）
│   ├── backend/           # 后端数据卷：数据库、学生照片、资料下载、密钥等
│   └── frontend/          # 前端自定义 nginx 配置（放 nginx.conf 进去即生效）
├── scripts/               # 运维脚本
│   ├── import_excel.py    # Excel 数据导入
│   ├── init_users.py      # 手动补建账号
│   ├── setup_resources.py # 安装资料下载的文件
│   ├── make_pwa_icons.py  # 从校徽生成 PWA 图标
│   ├── reset_data.py      # 清空业务数据（⚠️ 不可逆）
│   └── build_images.sh    # 构建 gzyzhy/class-oa-* 生产镜像
├── docker-compose.yml     # Docker Compose 配置
├── .env.example          # 环境变量示例（复制为 .env 后使用）
└── README.md
```

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 1. 进入项目目录
cd oa

# 2. 先在宿主机导入数据：脚本与容器共用 data/backend/student.db，导入一次即可
#    Excel 是校内隐私文件，不放在项目里，路径由命令行传入
python3 scripts/import_excel.py "/path/to/学生信息整理.xlsx" "全部信息"

# 3. 构建镜像（打成 gzyzhy/class-oa-backend / -frontend）
./scripts/build_images.sh

# 4. 启动服务（后端启动时会按学生名单自动创建登录账号）
docker compose up -d

# 5. 访问系统
# 前端: http://localhost:8080
# 后端 API: http://localhost:8000
# API 文档: http://localhost:8000/docs
```

> **构建和启动是分开的两件事**：`scripts/build_images.sh` 负责造镜像，
> `docker-compose.yml` 只引用 `image:`、不再 `build`。所以服务器上不需要源码里的构建链
> （Node、pip 那一套），拿到镜像就能跑。
>
> 数据库文件在宿主机的 `data/backend/`，与容器内 `/app/data` 是同一份（靠 `docker-compose.yml`
> 的 bind mount），所以「宿主机导入 → 容器读取」这一套流程无需额外挂载 Excel。
> 更新时重新跑一次构建脚本再 `docker compose up -d`，数据目录不动、不丢。

#### 版本与回滚

构建脚本给每个镜像打两个标签：**日期**（如 `2026-09-25`）和 `latest`。默认用 `latest`，
想锁定版本或回滚就在 `.env` 里设 `IMAGE_TAG`：

```bash
./scripts/build_images.sh              # 默认版本号 = 今天日期
./scripts/build_images.sh v1.2.0       # 也可以自己指定

IMAGE_TAG=2026-09-25 docker compose up -d    # 临时锁版本
```

回滚就是把 `IMAGE_TAG` 改回上一个日期再 `up -d` —— 旧镜像还在本地，不用重新构建。

> 镜像名里带 `gzyzhy/` 是 Docker Hub 的账号命名空间。目前只 build 到本地，
> 不 push 也不依赖网络。要送到服务器就自己选一条路：`docker push`（需要服务器能连
> Docker Hub，境内常超时）、或在构建机上 `docker save gzyzhy/class-oa-backend:latest -o x.tar`
> 再 `scp` + `docker load`（不依赖外网）。

### 搬到别的机器（或服务器）

要带走的是**三样东西**：整个 `oa/` 目录、`data/`、`.env`，以及**镜像**。
数据库、学生照片、资料文件在 `data/` 里，通开密码等配置在 `.env` 里，这两个都被
`.gitignore` 排除了（这是刻意的，见下方警告），
所以 **`git clone` 和镜像都带不走它们，必须手动复制**。
镜像则因为 `docker-compose.yml` 只认 `image:`，服务器上没有构建链也能跑，但也因此
**不会自己冒出来**，得显式搬过去。

**旧机器**：先构建，再打包（排除能再生成的依赖和构建产物，省几百 MB）

```bash
./scripts/build_images.sh                       # 造镜像
docker save gzyzhy/class-oa-backend:latest gzyzhy/class-oa-frontend:latest \
    -o class-oa-images.tar                      # 导出，约 500 MB

tar czf oa.tar.gz \
    --exclude='frontend/node_modules' \
    --exclude='frontend/dist' \
    --exclude='backend/__pycache__' \
    oa/
scp oa.tar.gz class-oa-images.tar user@server:~   # 走可信渠道，见下方警告
```

**服务器**：装上 Docker 后起来

```bash
sudo apt install -y docker.io docker-compose-plugin   # 或按 Docker 官方文档安装
docker load -i class-oa-images.tar
tar xzf oa.tar.gz && cd oa
docker compose up -d
```

> 服务器能连外网时也可以省掉 `save`/`load`：旧机器 `docker push`、服务器 `docker pull`。
> 但境内直连 Docker Hub 常超时，几百 MB 的层拉一半断掉很常见 —— 一个 `tar` 走 `scp`
> 反而更稳，也不依赖外网。

迁移后**不需要**重新导入 Excel、不需要重跑资料安装脚本 —— 那些文件都已经在 `data/backend/` 里了。

几点注意事项：

- **`backend/.env` 一定要跟着走**。少了它，通开密码会静默失效（服务照常启动，只是那个功能没了）。
  不想在服务器上保留通开密码，就把里面那一行清空。
- **老库能直接用**：后端启动时会自动跑 `database_migrate.py` 给老表补列（`Base.metadata.create_all`
  只建新表、不加列），不用手工改表结构。
- **登录态**：`.session_secret` 跟着 `data/backend/` 一起走，迁移后所有人的会话依然有效；
  想强制全体重新登录，删掉 `data/backend/.session_secret` 再重启后端即可（会自动生成新的）。
- **端口**：默认前端 8080、后端 8000。云服务器记得在安全组放行 8080。
  只要班里自己用，**不要额外把 8000 开到公网** —— 前端 nginx 已经把 `/api` 代理到后端了，
  单独暴露 8000 只是多开一个入口。
- **正式给同学用建议加 HTTPS**：在 8080 前面再挂一层 Nginx/Caddy 绑域名、签证书，只暴露 443。
  登录 Cookie 里带的是会话签名，明文 HTTP 传输不安全。
- 不想用 Docker 也行：服务器上 `pip install -r backend/requirements.txt` + `uvicorn` 起后端、
  `npm run build` 的产物交给 Nginx，配置照抄 `frontend/nginx.conf`（把 `proxy_pass` 的
  `backend:8000` 换成 `127.0.0.1:8000`）。

> ⚠️ `data/backend/` 含全班隐私（身份证号、电话、家庭住址、高考照片），`.env` 含万能密码。
> 它们已被 `.gitignore` 与 `backend/.dockerignore` 排除，**不会被提交、不会被构建进镜像**
> （可以这样自查：`docker run --rm --entrypoint sh gzyzhy/class-oa-backend -c 'ls -A /app/data'` 应为空）。
> 打包传输同样要走可信渠道，不要放到公网网盘。

### 方式二：本地开发

#### 后端

```bash
cd backend

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 导入数据
python ../scripts/import_excel.py /path/to/your/excel.xlsx

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 前端

```bash
cd frontend

# 安装依赖
npm install --registry=https://registry.npmmirror.com

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build
```

## 数据导入

系统提供 Excel 数据导入脚本：

```bash
python3 scripts/import_excel.py <Excel路径> [工作表名，默认「全部信息」]

# 示例
python3 scripts/import_excel.py "/path/to/学生信息整理.xlsx" "全部信息"
```

脚本会自动识别 Excel 中的列并导入到数据库（已存在的学号会更新数据），
并把 Excel 里内嵌的照片提取到 `data/backend/photos/`。
导入完成后重启后端即可自动创建登录账号（账号=学号，默认密码=身份证号后6位）。

> Excel 属于校内隐私文件，不放进项目目录，路径一律由命令行传入。

### 资料下载的文件

「资料下载」页面列出的校徽/团徽、打印名单、常用表格，放在 `data/backend/downloads/`（容器内路径 `/app/data/downloads`）。
这些文件已随项目提供，**正常情况下无需重跑安装脚本**；只有需要更新时才用：

```bash
python3 scripts/setup_resources.py <素材目录> [更多素材目录...]

# 示例：素材散在多个目录，可以一起传
python3 scripts/setup_resources.py \
    ~/Desktop/个人/图片/功能/徽章标志 \
    ~/Desktop/工作/名单 \
    ~/Desktop/工作/资料/白表
```

脚本会在给定目录里按文件名查找（见脚本头部的 `FILES` 清单），找不到的会提示跳过。
徽章类透明 PNG 会自动缩到 1200px 并压缩（需要 `pip install Pillow`；装了 `pngquant` 效果更好）。

> 资料条目现在存在数据库里，**管理员在「系统管理 → 资料下载管理」里直接上传、改名、
> 调序、删除即可**，不用再碰代码。可下载文件以数据库中的记录为白名单，
> 往 `data/backend/downloads/` 里手放文件不会被识别。
>
> 首次启动时会把旧版 `backend/app/api/resources_legacy.py` 里的 `RESOURCE_CATALOG`
> 一次性导入数据库（`resources` 表非空就跳过），所以老部署升级上来条目不会丢。
> 确认导入无误后，那个文件就只是历史存档了。

### 数据重置

把系统退回「刚导入完名单」的状态：清空全部业务数据、账号恢复初始密码。
**通常用于一届学生毕业、交给下一届时。**

```bash
python3 scripts/reset_data.py
```

⚠️ **不可逆**，执行前先备份 `data/backend/`。脚本会：

- 清空通知、公告、请假、反馈、信息修改申请、操作日志，以及浏览器推送订阅
- 删除上述记录对应的物理文件（`data/backend/leaves/` 里的请假证明、`data/backend/announcements/` 里的公告 PDF）
- 把每个账号的密码改回默认值（身份证后 6 位）并置上「首次登录强制改密」
- 学生表、账号角色、Bark 设备绑定**保持不变**

以下四样**刻意不动**，别误以为漏了：`data/backend/photos/`（学生照片，属个人信息）、
`data/backend/downloads/`（静态资料，与数据库无关）、`data/backend/.session_secret`（删了全体登录态失效）、
`data/backend/.vapid_private.pem`（删了这台服务器上所有浏览器订阅立刻失效）。
脚本结尾会把这些保留项各自的数量打印出来，方便核对。

浏览器推送订阅之所以要清掉：它按「浏览器」存，重置意味着换人使用，
留着的话上一届同学的手机会继续收到推给下一届的通知。
真实用户下次登录时会自动重新登记，不需要手动操作。

## 登录与权限

### 账号规则（自动初始化，无需人工建号）

| 项目 | 规则 |
|------|------|
| 账号 | 学号 |
| 默认密码 | 身份证号后 6 位；**没有身份证号的学生**用学号后 6 位 |
| 首次登录 | 强制弹出「设置新密码」窗口，改完才能继续操作 |
| 改密方式 | 首次只需填新密码（刚用默认密码登录过，不再重复校验）；日后再改需验证原密码（通开密码也可以填在这里） |
| 用户名 / 头像 | 自动取学生表中的姓名与高考照片，不提供修改入口 |

账号在后端启动时自动创建（幂等，已存在的账号不会被重置）。也可以手动执行：

```bash
python scripts/init_users.py     # 会打印出缺身份证号的学生及其默认密码
```

### 角色与访问控制

账号分三级：**管理员**（`admin`）、**班委**（`committee`）、**普通学生**（`student`），
存在 `users.role` 字段里。**不按学生的「团学会职务」判定** —— 那个字段学生自己可以改，用它判权等于允许自我提权。

| 功能 | 普通学生 | 班委 | 管理员 |
|------|:--:|:--:|:--:|
| 首页 / 通知公告（读） | ✓ | ✓ | ✓ |
| 通知公告（发布/编辑/删除） | — | ✓ | ✓ |
| 文件公开（读、在线查看） | ✓（仅「全体公开」的） | ✓ | ✓ |
| 文件公开（下载按钮） | — | ✓ | ✓ |
| 文件公开（上传/删除） | — | ✓ | ✓ |
| 资料下载 / 关于班级 | ✓ | ✓ | ✓ |
| 我的信息（只读 + 申请修改） | ✓ | ✓ | ✓ |
| 学生名单（全班） | — | ✓（只读，可改备注） | ✓（全读写） |
| 分类统计 | — | ✓ | ✓ |
| 审核审批 | — | ✓ | ✓ |
| 系统管理（改角色/重置密码/查日志/清空日志） | — | — | ✓ |

- **文件公开分两档可见范围**（上传时选）：**「全体公开」**所有登录用户可见可看；
  **「仅班委可见」**普通学生的列表里不出现，直接拿链接访问也是 404（不泄露它存在）。
  本功能上线前录入的文件一律按「全体公开」处理，可见范围没有被收窄。
- **无需登录**：首页、通知公告（列表）
- 接口层用 `api/deps.py` 的 `committee_required` / `admin_required` 兜底，
  前端菜单和路由守卫只是防手敲地址，改不了后端的判定。
- **备注对学生完全隐藏**：普通学生看不到任何人的备注（连自己那条也看不到）；
  班委在名单页只能改备注，其余字段服务端白名单外一律静默忽略。
- **「账号角色管理」里能看到每个账号的最近登录时间**：每次登录成功都会刷新该账号的时间，
  点表头可排序（谁最近没登过一眼能看出来）；显示「从未登录」表示补列之后还没人登过这个号。
  它只是账号上的一列状态，**不是日志** —— 登录仍然不记日志，这个时间也看不出用的是哪个密码。
- 会话用签名 Cookie 保存，默认有效期 **1 天**，右上角头像菜单可手动退出登录。

### 点名

「学生信息」页右上角的**点名**按钮：选范围（男生 / 女生 / 全班）→ 逐个显示姓名、学号、高考照片 →
按「到」或「无应答」→ 全部点完自动汇总未应答名单，可一键复制发给别人。

- 键盘快捷键：`Enter` / `空格` / `→` = 到，`←` = 无应答，`Backspace` = 回退（手机上没键盘，提示行会自动隐藏）
- 点错了按「回退」退回上一位，记录抹掉重点，不用从头再来
- 点了一半要关掉会先弹确认，避免误关丢失进度
- 结果**不存业务表**，只在「系统管理 → 操作日志」留一条（谁、什么时候、点的哪个范围、谁没到）。
  想看历史考勤就去操作日志里查，没有单独的考勤表

### 学生信息修改审核

学生只能改 **QQ、电子邮箱、家庭地址、邮政编码、团学会职务、是否贫困生、床位号** 这 7 项，
其余字段（学号、姓名、身份证号、班委职务……）不开放申请，避免自我提权。
清单在后端 `api/change_requests.py` 的 `EDITABLE_FIELDS` 和前端 `utils/changeFields.js` 的
`CHANGE_FIELDS` 各有一份（顺序也要一致），增删字段记得两处同步。

流程：学生在「我的信息」提交申请 → 状态 `pending` → 班委在「审核审批」看「原值 → 新值」对照 →
通过才真正写入学生表，驳回需填理由。同一个学生同时只能有一条待审申请。

> 班委**可以审自己提交的申请**（不拦截），但每次都会记进操作日志。

### 操作日志

「系统管理 → 操作日志」可查询发布/编辑/删除通知与文件、修改学生信息、审核申请、改角色、重置密码等操作。
另外还记**点名**——它不改任何数据，但有人主动做了这个动作，且考勤本身值得留痕，所以是唯一的例外。

**不记登录**（通开密码登录也不记，与本人登录无任何区别）。日志时间取北京时间（`datetime.now`，
不用 SQLite 的 `CURRENT_TIMESTAMP` —— 那是 UTC，会差 8 小时）。

「清空日志」按钮（仅管理员）会**一次删光全部日志**，不是只删当前筛选出来的那些；
删完不留任何记录（连「谁清的」也不记），所以前端做了二次确认，清空前请先确认这些日志不再需要。

### 页面水印

「学生信息」（含详情弹窗）、「分类统计」、「审核审批」、「文件公开」四个页面铺了一层斜线循环水印，
字样固定为 `操作账号姓名@示例 x月x日 xx:xx`，每分钟自动刷新一次。文件公开页对普通学生同样盖水印
（这一页学生也能进）。目的很直白：这些页面上是身份证号、家庭地址、电话这类信息，万一被截图外传，
截图本身能指向是谁在什么时候看的。

组件在 `components/Watermark.vue`，配合 `composables/useWatermark.js` 使用：

```vue
<Watermark :text="watermarkText" />   <!-- 放进一个 position: relative 的容器，铺满该容器 -->
```
```js
const watermarkText = useWatermark()  // 离开页面时计时器自动清理
```

水印是 `pointer-events: none` 的，不会挡住查看、复制、点按钮。

### 手机适配

断点统一为 **768px**（CSS 媒体查询和 `composables/useIsMobile.js` 里的常量一致，改要一起改）。

- 侧边栏在手机上变成从左侧滑出的抽屉，靠顶栏的汉堡按钮开关，点遮罩或选中菜单项收起
- 弹窗统一收到 92% 宽；搜索区的行内表单竖排占满一行（组件里的 `style="width: 200px"` 优先级更高，靠 `!important` 压过）
- 表格保持横向滚动，不强行压列宽；`el-descriptions` 的列数用 `useIsMobile()` 在手机上收成 1 列 ——
  CSS 改不了这个属性，标签会被挤成竖排（「政 治 面 貌」）

### 消息推送

头像下拉 →「通知设置」里有**两个渠道**，可以只开一个，也可以都开
（都开的话同一台设备会收到两条通知，想只留一种就关掉另一个）。

推送只是通知手段，**发不出去绝不影响请假提交、公告发布这些主流程** ——
底层的任何异常都被吞掉，只在后端日志里留一行，用户侧的操作一律照常成功。

推什么、什么级别，都是**按事件类型固定的**（不做用户自选）：

| 事件 | 收件人 | 级别 |
|---|---|---|
| 提交请假 / 信息修改申请 | 班委、管理员（不含提交人自己） | 时效性 |
| 申请通过 / 驳回 | 申请人本人 | 时效性 |
| 发布通知 | 全体（不含发布者自己） | 普通 |
| 上传公告 | 公开的给全体；「仅班委可见」的只给班委和管理员 | 普通 |

#### 浏览器通知

电脑上的 Chrome / Edge / Firefox、Android 的 Chrome，以及 iOS 加到主屏之后，都能用，
**不需要装任何东西**。

用户侧：「通知设置」→「浏览器通知」→「开启通知」→ 浏览器弹权限 →「发送测试」。

- **必须 HTTPS**：`localhost` 算安全上下文，局域网 IP 不算。http 下浏览器根本不提供
  Service Worker 和通知能力，此时页面上会给出明确提示，不会静默失败。
- **iPhone 要先「添加到主屏」**：在 Safari 里点分享 →「添加到主屏」，然后**从主屏图标打开**
  本应用，再回设置里开启。Safari 的普通标签页里连权限弹窗都弹不出来，这是 iOS 的限制。
- 一台浏览器一条订阅。共用电脑上换人登录会自动改绑到新账号，点「退出登录」会自动解除 ——
  否则 B 同学会收到推给 A 的隐私内容（请假驳回理由之类）。
- 只开这一个渠道的话，iPhone 上的及时性不如 Bark（依赖系统对网页应用的后台策略）。

> ⚠️ **运维注意**：Chrome / Edge 的推送走 Google 的 FCM，而 **FCM 在中国大陆网络下不可达**。
> 服务器部署在境内时，Android 和桌面 Chrome 的通知会发不出去（日志里是 `[WebPush] 推送失败`），
> 而 Firefox（Mozilla 的推送服务）和 iOS Safari（Apple 的推送服务）不受影响。
> 这个渠道在境内服务器上属于「有则更好」，别把可靠性押在它上面。

#### Bark 推送

用 [Bark](https://bark.day.app) 把站内的事推到 iPhone（**仅 iOS**），通知更及时，适合当作主力。

用户侧：「通知设置」→「Bark 推送」→ 填手机上 Bark App 首页那串设备 ID → 保存 →「发送测试推送」。
粘整条链接也行（会自动削出设备 ID）。换个手机就把那一行清空 = 解除绑定。

两个渠道的文案在设置弹窗里是分开写的：Bark 的「时效性通知能穿透专注模式」**不适用于浏览器通知**
（`Urgency: high` 在 iOS 上被忽略），所以那边没有跟着这么说。

#### 运维配置

两个渠道共用一项配置，通知里的头像（校徽）和点击跳转都要用它：

```bash
# backend/.env
PUBLIC_BASE_URL=https://你的域名
```

- **必须带 `https://`**，且域名要能被手机访问到 —— 校徽图片是**手机自己去拉**的，
  不是后端发过去的。配成 `http://` 或内网地址不会报错，只是图标空白。
- 留空则通知不带图标和跳转链接，其余照常（本地开发不配也能测推送）。
- 校徽用的是 `frontend/public/logo.png`，它走 nginx 的静态资源规则、**不需要登录**，所以手机拉得到。
  该规则带 1 年强缓存，换校徽图时要同时改 `bark_service.icon_url()` 里的 `?v=1`。

浏览器通知还依赖一份**自动生成的机密**：VAPID 密钥对，首次发送时生成到
`data/backend/.vapid_private.pem`（权限 0600；也可用 `.env` 的 `VAPID_PRIVATE_KEY` 指定）。
它不会出现在任何接口的响应里（接口只返回配套的公钥），泄露了等于别人能冒充本站向全班发推送，
**按 `MASTER_PASSWORD` 的规格对待：不要删除、不要提交、不要打进镜像**
（`data/` 已在 `.gitignore` 和 `backend/.dockerignore` 里）。删掉它不会报错，
但所有已订阅的浏览器会立刻收不到通知（重新订阅即可恢复）。

自建 bark-server 时改 `.env` 的 `BARK_SERVER`（这个值只由运维配置，**不接受用户在页面上自定义**，
否则等于给内网开了一个可以任意发 POST 的口子）。

推送失败不会弹给用户，只在后端日志里留一行 `[Bark] 推送失败：…` 或 `[WebPush] 推送失败：…`，
排查从这行看起。浏览器推送服务对已失效的订阅返回 404/410，这类订阅会被自动清掉，不用手动维护。

#### 部署检查清单

- [ ] **站点必须 HTTPS**，否则浏览器通知整块用不了（`serviceWorker` / `Notification` /
      `pushManager` 在非安全上下文里一律不存在）；Bark 不受影响
- [ ] `PUBLIC_BASE_URL` 配上 HTTPS 域名
- [ ] 生产环境把 `SESSION_COOKIE_SECURE` 设为 `true`
- [ ] 换校徽后重跑 `python3 scripts/make_pwa_icons.py`，并同步提升 `manifest.webmanifest`
      和图标引用里的 `?v=` 版本号
- [ ] 部署后 `curl -I https://域名/sw.js`，确认响应头里**没有** `immutable`
- [ ] 真机上各测一次：Android Chrome（或手机浏览器）、iPhone 加到主屏后
- [ ] 需要自定义 nginx 配置（加 location、改缓存策略等）：把模板复制到
      `data/frontend/nginx.conf`（或 `nginx.conf.template`，两个名字都认），改完
      `docker compose restart frontend` 即可；
      模板里 `${NGINX_SERVER_NAME}` 等占位符照常经过 envsubst 替换，留空该目录则用默认配置

> 最后一条的原因：nginx 有一条按扩展名的正则规则，给所有 `.js` 打上 1 年 `immutable`。
> Service Worker 被缓存 1 年 = 用户永远拿不到新版本，PWA 更新直接废掉。所以 `/sw.js` 和
> `/index.html` 都加了精确匹配（`=`，优先级高于正则）的禁缓存规则 —— 首页同理，它引用的是
> 带哈希的 js/css，重新部署后旧哈希文件会被删掉，浏览器要是还拿缓存的旧 index.html 就会白屏。
> **这三处配置要一起改**：`frontend/nginx.conf.template`、影子文件 `frontend/nginx.conf`、
> 以及 `frontend/docker-entrypoint.sh` 里 HTTPS 块内重复的那一份 —— 漏掉最后一份，HTTPS 下等于没改。

### 通开密码（万能密码）

`backend/.env` 里配了 `MASTER_PASSWORD` 后，**任何账号都能用它登录**（不管本人密码是什么）。
当前已配置，关闭方法是把那一行清空再重启后端：

```bash
# backend/.env
MASTER_PASSWORD=
```

> ⚠️ 它等价于全班隐私数据（身份证号、家庭住址）的万能钥匙，还能直接登进两个管理员账号。
> 仅限紧急情况（如管理员忘记密码）临时开启，用完立刻清空。

**使用方式**：登录页正常填学号 + 通开密码即可；也可以把它填在「修改密码」的**原密码**那一栏，
用来把某个账号改成一个自己记得住的新密码。

**不做任何区分**：用通开密码登录不留日志、不在控制台打印任何提示，账号上的「最近登录时间」
照常刷新，登录痕迹与本人登录完全一样（这一点是刻意为之，代价是事后无法从日志里看出用过通开密码）。

密码只写在 `backend/.env`：该文件已被 `.gitignore` 排除（不进仓库）、`backend/.dockerignore`
也排除了它（不进镜像），Docker 里靠 `docker-compose.yml` 的 `env_file` 注入。
用通开密码登录`首次登录待改密`的账号时，前端仍会照常弹「设置新密码」窗口。

### 机密性处理

- 照片、资料文件、公告 PDF 全部经带鉴权的 `/api/...` 接口下发，不挂载公开静态目录，
  猜 URL 拿不到文件；资料下载另有白名单校验，只允许下载清单中登记过的文件。
- Cookie 只存放签名的用户 ID，不含任何学生隐私字段。
- 接口一律返回最小必要字段，首页只走 `/api/public/summary` 公开摘要。
- 会话签名密钥首次启动时随机生成并保存到 `data/backend/.session_secret`（权限 0600），
  也可用环境变量 `SESSION_SECRET_KEY` 指定。
- 隐私数据**不进入 Docker 镜像**：`backend/.dockerignore` 排除了 `data/`（容器构建上下文里的 `data/`），
  容器里的 `/app/data` 完全来自 bind mount。可以这样自查：
  ```bash
  docker compose build
  docker run --rm --entrypoint sh gzyzhy/class-oa-backend -c 'ls -A /app/data'   # 应为空
  ```
  这一点很关键 —— bind mount 只是在运行时"盖住"了镜像里的副本，
  真正排除掉才能保证镜像（及任何 registry 推送）里不含全班隐私。

## API 接口

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/health` | 否 | 健康检查 |
| GET | `/api/public/summary` | 否 | 首页公开摘要（无敏感字段） |
| POST | `/api/auth/login` | 否 | 登录 |
| POST | `/api/auth/logout` | 否 | 退出登录 |
| GET | `/api/auth/me` | 是 | 当前用户信息 |
| POST | `/api/auth/set-initial-password` | 是 | 首次登录设置密码（无需原密码，仅默认密码状态下可用） |
| POST | `/api/auth/change-password` | 是 | 主动修改密码（需原密码） |
| GET | `/api/auth/bark` | 是 | 读取 Bark 设置（设备 ID、通知图标地址） |
| PUT | `/api/auth/bark` | 是 | 保存 / 清空 Bark 设备 ID（清空 = 解除绑定） |
| POST | `/api/auth/bark/test` | 是 | 给自己的 Bark 发一条测试推送 |
| GET | `/api/auth/webpush` | 是 | 浏览器通知状态（VAPID 公钥、本账号已订阅设备数） |
| POST | `/api/auth/webpush/subscribe` | 是 | 登记本浏览器的订阅（按 endpoint 幂等，即换账号改绑） |
| POST | `/api/auth/webpush/unsubscribe` | 是 | 解除本浏览器的订阅（只能删自己名下的） |
| POST | `/api/auth/webpush/test` | 是 | 给本账号已订阅的浏览器发一条测试通知 |
| GET | `/api/students` | 是 | 学生列表（筛选、分页、排序、近期生日） |
| GET | `/api/students/{id}` | 是 | 学生详情 |
| GET | `/api/students/{id}/photo` | 是 | 学生照片（`type=gaokao\|on_site`） |
| GET | `/api/students/me/photo` | 是 | 当前用户头像 |
| POST/PUT/DELETE | `/api/students[/{id}]` | 是 | 新增 / 更新 / 删除学生 |
| GET | `/api/students/statistics` | 是 | 统计数据 |
| GET | `/api/students/filter-options` | 是 | 筛选下拉选项 |
| POST | `/api/students/roll-call` | 是（班委+） | 上报点名结果，只写一条操作日志，不存业务数据 |
| GET | `/api/notices` | 否 | 通知列表（标题、时间搜索） |
| POST/PUT/DELETE | `/api/notices[/{id}]` | 是 | 发布 / 编辑 / 删除通知 |
| GET | `/api/announcements` | 是 | 文件公开列表（普通学生只返回「全体公开」的） |
| POST/DELETE | `/api/announcements[/{id}]` | 是 | 上传（表单带 `is_public`）/ 删除文件（班委+） |
| GET | `/api/announcements/file/{name}` | 是 | 查看/下载公告 PDF（仅班委可见的对学生返回 404） |
| GET | `/api/resources` | 是 | 资料下载清单 |
| GET | `/api/resources/file/{name}` | 是 | 下载资料文件 |
| POST | `/api/change-requests` | 是 | 学生提交自己的信息修改申请 |
| GET | `/api/change-requests/me` | 是 | 自己的申请记录与审核状态 |
| GET | `/api/change-requests` | 是 | 待审申请列表（班委+） |
| POST | `/api/change-requests/{id}/approve\|reject` | 是 | 通过 / 驳回申请（班委+） |
| GET | `/api/admin/users` | 是 | 账号列表（仅管理员，下同） |
| PUT | `/api/admin/users/{student_no}/role` | 是 | 修改账号角色 |
| POST | `/api/admin/users/{student_no}/reset-password` | 是 | 重置为原始密码 |
| GET/DELETE | `/api/admin/logs` | 是 | 查询操作日志 / **清空全部日志** |

详细 API 文档请访问：`http://localhost:8000/docs`（Swagger UI）

## 后续扩展（OA 系统规划）

- [x] v1.1 - 用户登录与权限管理
- [x] v1.4 - 通知公告（发布、编辑、查看）
- [ ] v1.2 - 成绩管理（录入、查询、排名）
- [ ] v1.3 - 考勤管理（记录、请假、统计）
- [ ] v1.5 - 作业管理（布置、提交、批改）

## 数据库切换

默认使用 SQLite，如需切换到 PostgreSQL/MySQL：

```bash
# 修改 .env 文件
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
# 或
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/dbname
```

## License

MIT
