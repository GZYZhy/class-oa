# API 参考

> 版本 1.17.14，共 256 个接口。
> 本文由 `scripts/gen_api_docs.py` 从 FastAPI 的 OpenAPI 描述自动生成，接口变动后重新运行该脚本即可。

## 通用约定

- **基础地址**：下文路径都带 `/api` 前缀，直接拼在站点域名后，例如 `https://oa.example.com/api/inbox`。
- **认证（浏览器）**：调用 `POST /api/auth/login` 登录，服务端会种下 HttpOnly 会话 Cookie，之后的请求带上它即可；「保持登录」决定关闭浏览器后是否失效。
- **认证（脚本）**：在「账号安全 → 访问令牌」里创建 `oa_pat_` 开头的令牌，请求头写 `Authorization: Bearer <令牌>`。**令牌一律按学生身份处理** —— 班委 / 管理员专属接口用令牌调用会返回 403；创建、吊销令牌以及改密码等操作也只允许网页会话调用。令牌有调用频率限制，超限返回 429。
- **失败格式**：出错时返回 `{"detail": "原因"}`，`detail` 是可直接展示给用户的中文。401 = 未登录或会话失效，403 = 权限不足，404 = 不存在或无权查看。
- **参数校验失败**：一律 422，`detail` 里逐条列出是哪个字段、错在哪。
- **分页**：需要分页的列表接口接受 `page`（从 1 开始）和 `page_size`，返回里带 `total` / `page` / `page_size`。
- **时间**：响应里是北京时间，形如 `2026-10-17T08:30:00`；传日期参数用 `YYYY-MM-DD`，传日期时间用同样的 ISO 格式。
- **权限**：每个接口需要什么身份，写在它下方的「说明」里；没写「需登录」的公开接口，未登录也能调用。

## 目录

- 公开信息（1）
- 认证（25）
- 初始化（2）
- 通知公告（10）
- 学生信息（19）
- 文件公开（4）
- 资料下载（2）
- 关于班级（1）
- 修改申请（6）
- 请假申请（16）
- 考勤记录（9）
- 签到（12）
- 意见反馈（8）
- 未读红点（1）
- 电动车通行证（17）
- 学生信息导出（7）
- 证明开具（16）
- 办件空间（2）
- 站内信（4）
- 生日关怀（4）
- 投票（12）
- 成绩（12）
- 日程（14）
- 签字（9）
- 通行密钥（6）
- 二次验证（9）
- 系统管理（27）
- 健康检查（1）

## 公开信息

### 首页公开摘要

`GET /api/public/summary`

**响应**

- `200` — 成功

## 认证

### 获取验证码（SVG 图片）

`GET /api/auth/captcha`

生成一道算术题，答案存会话里，下一次登录时校验。 验证码 SVG 直接返回，不需要额外 id —— 未登录用户也有会话 Cookie， 答案就存在 session["captcha_answer"] 里。 每次调用都会刷新答案。

**响应**

- `200` — 成功

### 当前 IP 是否需要人机验证，以及用哪一种

`GET /api/auth/captcha-required`

登录页先问一下要不要显示验证码框，免得每次都加载 SVG。 required 为 False 时也要带上 mode / site_key：前端要靠它知道 「等会儿万一输错了，该去加载 Turnstile 控件还是拉算术题」。 site key 本来就是公开的（它要发给浏览器），secret key 永远不出后端。 顺带带上 banned / banned_until：让登录页能**直接**显示「本机 IP 已被封禁， X 解除」，而不是等用户填完表单吃了 403，还先看到一张永远用不上的验证码。

**响应**

- `200` — 成功

### 登录

`POST /api/auth/login`

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `student_no` | string | 是 | 学号 |
| `password` | string | 是 | 密码 |
| `remember` | boolean | 否 | 是否保持登录 7 天 |
| `captcha` | string，可空 | 否 | 算术验证码的答案（失败 1 次后必填） |
| `turnstile_token` | string，可空 | 否 | Turnstile 控件给的 token |

**响应**

- `200` — 成功

### 退出登录

`POST /api/auth/logout`

**响应**

- `200` — 成功

### 当前用户信息

`GET /api/auth/me`

刷新页面时前端靠这个接口恢复登录状态 所以这里不能依赖 get_current_student —— 域外账号没有学生记录， 那样会让它一刷新就被当成未登录踢回登录页。

**响应**

- `200` `UserInfoResponse` — 成功
  - 字段：`student_no`、`name`、`avatar`、`class_name`、`role`、`must_change_password`、`is_external`、`is_bootstrap`、`bark_key`、`smtp_enabled`

### 当前用户头像

`GET /api/auth/avatar`

u 参数仅用于前端绕过浏览器缓存（切换账号时 URL 不同），后端不使用

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `u` | query | 否 | string |  |

**响应**

- `200` — 成功

### 首次登录设置密码（无需原密码）

`POST /api/auth/set-initial-password`

首次登录专用：用户刚用默认密码完成登录，再要求重复输入一遍原密码没有意义 该接口只在 still-default 状态下可用，改过一次后即失效

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `new_password` | string | 是 |  |

**响应**

- `200` — 成功

### 修改密码（需原密码）

`POST /api/auth/change-password`

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `old_password` | string | 是 |  |
| `new_password` | string | 是 |  |

**响应**

- `200` — 成功

### 列出我的访问令牌

`GET /api/auth/tokens`

只列自己的，**永远不返回明文和 hash** 明文在创建那一次的响应里给出之后就取不回来了，这里只能看到前缀。 用 require_cookie_auth 而不是 get_current_user：令牌不该能管理令牌。

**响应**

- `200` `AccessTokenList` — 成功
  - 字段：`items`、`max_count`

### 创建访问令牌

`POST /api/auth/tokens`

创建一把访问令牌，**明文只在这一个响应里返回** 令牌在权限上等同于「该账号的学生身份」——哪怕持有人是管理员， 用它也只能读到、操作自己相关的数据（见 deps.py 的 _user_from_pat）。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 备注名，用来区分这把令牌是干嘛的 |
| `days` | integer（默认 90） | 否 | 有效期天数：30 / 90 / 365，0 表示不限期 |
| `password` | string | 是 | 登录密码，二次确认用 |

**响应**

- `200` `AccessTokenCreated` — 成功
  - 字段：`id`、`name`、`token`、`expires_at`

### 吊销访问令牌

`DELETE /api/auth/tokens/{token_id}`

只能吊销自己的。 归属条件直接写进查询条件，不做「先按 id 查到再比对 owner」—— 后者一旦忘了比对就是水平越权。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `token_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 我的日志

`GET /api/auth/my-logs`

本人自助查看两块，和「系统管理 → 账号管理 → 查日志」共用同一套查询： - 操作日志：我**作为操作人**留下的记录（发布通知、审核办件、点名……），分页 - 登录与账号操作：我自己的登录 / 改密 / 令牌与钥匙增删 / 二次验证设置， 最近 7 天，窗口内分页 两块各自独立分页（page / events_page），因为一个是全量历史、一个是 7 天窗口， 共用一个页码会互相打架。 故意不给「被操作记录」（别人对我做了什么）：那是管理员视角。本人看不了 别人对自己账号做过什么，也就少一处能反推出管理员操作的入口。 账号事件只记成功事件，登录失败不记 —— 别人拿错密码试的 IP 不该被看到。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤200，默认 20） | 默认 `20` |
| `events_page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `events_page_size` | query | 否 | integer（≥1，≤200，默认 20） | 默认 `20` |

**响应**

- `200` `MyLogsResponse` — 成功
  - 字段：`operations`、`events`、`events_total`、`events_since`

### 读取我的 Bark 推送设置

`GET /api/auth/bark`

只读自己的，暴露不出别人的设备 key

**响应**

- `200` — 成功

### 保存或解除 Bark 推送设置

`PUT /api/auth/bark`

传空串即解除绑定（换手机时用）

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `bark_key` | string | 否 |  |

**响应**

- `200` — 成功

### 发一条测试推送

`POST /api/auth/bark/test`

这里同步发送、如实返回成败 别处都走后台任务（不拖慢接口），但测试推送是用户正盯着看的操作， 需要当场告诉他 key 对不对，所以等结果。 只发库里存的 key，不接受请求体传进来的 —— 否则任何登录用户都能拿这个接口 当「任意 Bark 设备轰炸器」。

**响应**

- `200` — 成功

### 读取浏览器通知状态

`GET /api/auth/webpush`

返回订阅所需的公钥，以及本账号已订阅的设备数 公钥是要发到浏览器里去的，不算机密；真正保密的是配套的私钥， 它只躺在服务器的 data/.vapid_private.pem 里，任何接口都不会返回。

**响应**

- `200` — 成功

### 登记浏览器通知订阅

`POST /api/auth/webpush/subscribe`

浏览器订阅后把订阅信息交给后端存下来 同一个 endpoint 再提交一次是**改绑**，不是新增（一台电脑换个人登录走的就是这条路）， 所以这个接口是幂等的，前端可以放心重复调用。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `endpoint` | string | 是 |  |
| `keys` | WebPushKeysRequest | 是 |  |

`keys` 的字段：

  - `p256dh`：string（必填）
  - `auth`：string（必填）

**响应**

- `200` — 成功

### 解除浏览器通知订阅

`POST /api/auth/webpush/unsubscribe`

只删自己名下的那条，传别人的 endpoint 进来也删不掉

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `endpoint` | string | 是 |  |

**响应**

- `200` — 成功

### 发一条测试通知到自己的浏览器

`POST /api/auth/webpush/test`

同步发送、如实返回成败（和 Bark 测试推送一个思路） 只发库里当前账号的订阅，不接受请求体传 endpoint —— 否则任何登录用户 都能拿这个接口当「任意设备轰炸器」。

**响应**

- `200` — 成功

### 读取我的自定义 webhook 设置

`GET /api/auth/webhook`

只读自己的。别人的地址读不到 —— 那里面通常内嵌着密钥

**响应**

- `200` — 成功

### 保存自定义 webhook 设置

`PUT /api/auth/webhook`

只做本地校验后落库，**不发起任何网络请求** 早先打算「保存时顺便测一下，测不通就不给存」，那是错的：不少接收端会校验签名 或固定字段，对测试包直接回 401 —— 于是配置明明是对的，用户却永远存不上， 只能反复改一个没问题的地方。改成一保存就落库、测试走单独的 /test 端点， 用法和 Bark 完全一致；前端「发送测试」按钮是「先保存再发」，用户看到的一样。 「发不发」看 data.enabled，「发到哪」看 data.url。地址非空时完整校验一遍： 形态 + **域名解析出来的每个 IP 都必须是公网**。校验失败返回 400 带一句能直接 显示给用户的原因。 地址为空时强制归一成关闭：webhook 没有「学生档案邮箱」那种回退地址，空着地址 还开着开关就是个永远发不出去的状态，留在库里只会让人下次打开设置页时困惑。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `url` | string | 否 | 要 POST 过去的 https 地址；空 = 没配地址 |
| `template` | string | 否 | 请求体 JSON 模板；空 = 用内置默认模板 |
| `enabled` | boolean，可空 | 否 | 是否往这个地址发通知；不传 = 沿用旧规则 |

**响应**

- `200` — 成功

### 往我配置的地址发一条测试通知

`POST /api/auth/webhook/test`

同步发送、如实返回成败（同 Bark / 浏览器推送的测试端点） **只发库里已经存好的地址，不接受请求体传 URL** —— 否则任何登录用户都能拿这个 接口当「任意地址 POST 器」，整套 SSRF 防护就从这儿被绕过去了。 **不看开关**：测试是「验证这个地址配得对不对」，和「现在要不要收通知」是两件事。 关着的时候也该能测，不然用户只能先开、收到一堆通知，才发现地址是错的。 邮件那边同一条口径（test_email_notify 也不看 notify_email_enabled）。

**响应**

- `200` — 成功

### 读取我的邮件通知设置

`GET /api/auth/email-notify`

default_email 是学生档案里**可用**的邮箱，给前端显示「留空就用 xxx」 只回可用的：真实库里有 2 个缺 @ 的邮箱（Excel 导入带进来的，形如 3681914218qq.com）。原样回给前端的话，页面上会写「留空则用 3681914218qq.com」， 而那个地址根本发不出去 —— 等于当着用户的面撒谎。回空串，前端改说 「档案里的邮箱不可用，请自己填一个」，和 PUT 的提示口径一致。 域外账号没有学生记录，也是空串 —— 前端据 is_external 换成「得自己填一个」 （它压根没有档案可以回退）。**这里只读，不写。**

**响应**

- `200` — 成功

### 保存我的邮件通知设置

`PUT /api/auth/email-notify`

**只写 users 表，绝不回写 students** 这也是「地址覆盖值放在 users 而不是复用 students.email」的原因：学生档案只能 由「基本信息 → 修改」那条审批流改，从表结构上就杜绝了「在这里顺手把档案改了」。 页面上的说明文案和这一点必须对得上。 管理员还没配 SMTP 时也允许保存 —— 等他配好就立即生效，不用麻烦用户再来一次。 但接口会如实说明现在开了也收不到，前端那边整块也是置灰的。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | string | 否 | 收通知的邮箱；空 = 用学生档案邮箱 |
| `enabled` | boolean | 否 | 是否接收通知邮件 |

**响应**

- `200` — 成功

### 给我自己发一封测试邮件

`POST /api/auth/email-notify/test`

同步发送、如实返回成败 **只发给当前账号自己的地址，不接受请求体传地址** —— 否则这就成了一个 人人可用的发信接口：可以拿它伪造出发自本站的邮件去轰炸别人， 而我们域名的 SPF 记录还会替这些信背书。

**响应**

- `200` — 成功

## 初始化

### 初始化状态

`GET /api/setup/state`

还差不差东西 只读，任何登录用户都能问（完成后前端偶尔还会问一次，返回 needs_setup=false）。

**响应**

- `200` `SetupStateResponse` — 成功
  - 字段：`needs_setup`、`has_students`、`students`

### 完成初始化：指定管理员并废止临时账号

`POST /api/setup/finish`

把指定学号设为管理员；条件满足则当场删掉临时账号 只允许**临时账号自己**调：不然这就成了管理员改角色的一个侧门， 绕过了系统管理页那套操作日志。真实的提权走 PUT /api/admin/users/{no}/role。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `admin_student_no` | string | 是 |  |

**响应**

- `200` — 成功

## 通知公告

### 通知列表

`GET /api/notices`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `title` | query | 否 | string，可空 | 按标题搜索（模糊） |
| `start_date` | query | 否 | string，可空 | 发布时间起始 |
| `end_date` | query | 否 | string，可空 | 发布时间截止 |
| `limit` | query | 否 | integer（≥1，≤100），可空 | 只返回最新 N 条（首页用） |

**响应**

- `200` — 成功
  - 字段：NoticeResponse[]

### 发布通知（班委及以上）

`POST /api/notices`

发布通知（multipart form：正文 + 附件一起发）

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 标题 |
| `publish_date` | string | 是 | 发布时间 |
| `content` | string | 是 | 正文（Markdown） |
| `attachments` | string[] | 否 | 附件，最多 3 个 |

**响应**

- `200` `NoticeResponse` — 成功
  - 字段：`id`、`title`、`publisher`、`publish_date`、`content`、`attachments`、`editors`、`created_at`、`updated_at`、`is_read`

### 标记为已读

`POST /api/notices/{notice_id}/read`

展开通知时前端调它。重复调用无副作用（唯一约束兜底）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `notice_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 通知已读情况（班委及以上）

`GET /api/notices/{notice_id}/reads`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `notice_id` | path | 是 | integer |  |

**响应**

- `200` `NoticeReadStatus` — 成功
  - 字段：`total`、`read_count`、`rows`

### 提醒未读的人（班委及以上）

`POST /api/notices/{notice_id}/remind`

给「还没读这条通知」的人各推一条提醒 名单直接用已读清单那份（read_status 的分母是 users 全表）。三条口径： - **冻结账号跳过**：他们本来就读不了通知（读接口会拒），推了也白推 - **操作人自己跳过**：他正对着这条通知点「提醒未读」，再给自己推一条纯属噪音 （发布通知那条链路也是这么排除自己的，口径一致） - 域外账号照推：名单里有他们，说明这条通知本来就发给了他们 前两条都要在前端算按钮上的「未读 N 人」时同样排除，否则按钮说 3 人、 提示说「已提醒 1 人」，班委会以为漏推了。 逐个人调 recipients(only_no=...)，不给 recipients 加「批量学号」参数 —— 那要 同时改 bark / webpush / email / webhook 四个渠道服务，而班级规模几十人、未读 通常十几人，循环几个查询在这个量级上更简单也更不容易改错。**别改成批量查询**。 recipients 必须在请求处理过程中调用（响应发出去之后 get_db 会把会话关掉， 见 notify_service.recipients 的注释），所以循环和 commit 都留在请求里。 不写操作日志的话，「我为什么收到这条提醒」事后查不到任何记录 —— 一次给几十人推送是对他们可见的动作，值得留痕。 返回值从前还有一个 unreachable（没读、但四个渠道一个都没订阅、因此什么都 收不到的人）。**加站内信之后这类人不存在了**：提醒一定落进对方的收件箱， 所以「已提醒 N 人」就是 N 个人真收到了，不用再分两类说。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `notice_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载通知附件

`GET /api/notices/{notice_id}/attachments/{index}`

按通知 id 和附件下标下载；通知是公开的，所有人（含未登录）都能下载

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `notice_id` | path | 是 | integer |  |
| `index` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 获取通知订阅链接

`GET /api/notices/rss/token`

获取通知公告的 RSS 订阅链接（需登录） 用的是「我的日程」那**同一个**订阅令牌（ical_tokens 表）—— 不用新建表、 不用迁移。代价是在日程页重置令牌会让这条 RSS 链接一起失效，前端文案里写明了。

**响应**

- `200` `ICalTokenResponse` — 成功
  - 字段：`token`、`url`、`last_accessed_at`

### 通知公告 RSS 订阅

`GET /api/notices/rss/{token}.xml`

RSS 订阅端点（通过 URL 里的 token 鉴权，无效一律 404） 这里**故意不设** Cache-Control，于是拿到的是默认的 no-store （DefaultCacheControlMiddleware 那个）。刷新节奏交给 feed 里的 <ttl>， 不在这层做 HTTP 缓存 —— 订阅源本来体量就小，读者端也按自己的节奏轮询。 （2026-10 之前不设还有另一层原因：当时的 no-store 写在前端 nginx 里， 而 add_header 是追加不是覆盖，这里就算写了也会被顶掉。那句已经搬进后端， 现在「设了就生效」—— 哪天要给订阅源加缓存，直接写就行，不用再绕。 课表订阅源 /api/schedules/.../ical 就是自己设了 max-age=3600 的例子。）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `token` | path | 是 | string |  |

**响应**

- `200` — 成功

### 编辑通知（班委及以上）

`PUT /api/notices/{notice_id}`

编辑通知：正文和附件都能改。 附件处理逻辑： - keep_attachments: 要保留的原附件下标（JSON 数组字符串），不传或为空表示全部保留 - attachments: 新上传的附件 - 最终附件列表 = 保留的原附件 + 新上传的附件，总数不超过 MAX_ATTACHMENTS - 被去掉的原附件文件会被删除

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `notice_id` | path | 是 | integer |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 标题 |
| `publish_date` | string | 是 | 发布时间 |
| `content` | string | 是 | 正文（Markdown） |
| `attachments` | string[] | 否 | 新增附件，最多 3 个（含原有） |
| `keep_attachments` | string | 否 | 保留的原附件下标（JSON 数组，如 [0,2]） |

**响应**

- `200` `NoticeResponse` — 成功
  - 字段：`id`、`title`、`publisher`、`publish_date`、`content`、`attachments`、`editors`、`created_at`、`updated_at`、`is_read`

### 删除通知（班委及以上）

`DELETE /api/notices/{notice_id}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `notice_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

## 学生信息

### 学生列表（支持筛选、搜索、排序）

`GET /api/students`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤500，默认 20） | 默认 `20` |
| `keyword` | query | 否 | string，可空 |  |
| `gender` | query | 否 | string，可空 |  |
| `ethnicity` | query | 否 | string，可空 |  |
| `political_status` | query | 否 | string，可空 |  |
| `hometown` | query | 否 | string，可空 |  |
| `dormitory` | query | 否 | string，可空 |  |
| `class_position` | query | 否 | string，可空 |  |
| `league_position` | query | 否 | string，可空 |  |
| `is_poor` | query | 否 | string，可空 |  |
| `school_status` | query | 否 | string，可空 |  |
| `birthday_days` | query | 否 | integer（≥1，≤365），可空 |  |
| `sort_by` | query | 否 | string，可空 |  |
| `sort_order` | query | 否 | string | 默认 `asc` |

**响应**

- `200` `StudentListResponse` — 成功
  - 字段：`total`、`items`

### 新增学生（仅管理员）

`POST /api/students`

新增学生，并同步给他开一个登录账号 密码规则与批量建号（`scripts/init_users.py`）完全一致，共用 `default_password`： 身份证号后 6 位；还没有身份证号的新生（刚入学常见）退化成学号后 6 位 —— 那种情况下接口会把明文回带，因为学号后 6 位本来就不是秘密，回带是为了让 管理员知道要单独提醒谁去改密。账号建成即带「首次登录必须改密」标记。 注意：管理员事后补录身份证号**不会**改动已设的密码 —— 密码只在建号、 重置这两个时点确定，避免改个资料就把人的密码悄悄换掉。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `student_no` | string | 是 | 学号 |
| `name` | string | 是 | 姓名 |
| `gender` | string，可空 | 否 | 性别 |
| `major` | string，可空 | 否 | 专业 |
| `class_name` | string，可空 | 否 | 班级 |
| `birth_date` | string，可空 | 否 | 出生日期 |
| `ethnicity` | string，可空 | 否 | 民族 |
| `political_status` | string，可空 | 否 | 政治面貌 |
| `hometown` | string，可空 | 否 | 生源地 |
| `id_card` | string，可空 | 否 | 身份证号 |
| `exam_no` | string，可空 | 否 | 考生号 |
| `exam_category` | string，可空 | 否 | 考生类别 |
| `subject_type` | string，可空 | 否 | 科类 |
| `exam_type` | string，可空 | 否 | 考试类型 |
| `admission_batch` | string，可空 | 否 | 录取批次 |
| `gaokao_score` | integer，可空 | 否 | 高考总分 |
| `high_school` | string，可空 | 否 | 毕业中学 |
| `registration_status` | string，可空 | 否 | 报到状态 |
| `registration_time` | string（日期时间），可空 | 否 | 报到时间 |
| `school_status` | string，可空 | 否 | 在校状态 |
| `phone` | string，可空 | 否 | 本人电话 |
| `family_phone` | string，可空 | 否 | 家庭电话 |
| `qq` | string，可空 | 否 | QQ号码 |
| `email` | string，可空 | 否 | 本人电子邮箱 |
| `family_address` | string，可空 | 否 | 家庭通信地址 |
| `postal_code` | string，可空 | 否 | 邮政编码 |
| `dormitory` | string，可空 | 否 | 宿舍 |
| `bed` | string，可空 | 否 | 床位 |
| `class_position` | string，可空 | 否 | 班委职务 |
| `league_position` | string，可空 | 否 | 团学会职务 |
| `is_poor` | string，可空 | 否 | 是否贫困生 |
| `remark` | string，可空 | 否 | 备注 |
| `gaokao_photo` | string，可空 | 否 | 高考照片URL |
| `on_site_photo` | string，可空 | 否 | 实地采集照片URL |
| `id_photo` | string，可空 | 否 | 自备证件照URL |

**响应**

- `200` `StudentCreateResponse` — 成功
  - 字段：`message`、`student`、`password`、`fallback`

### 统计数据

`GET /api/students/statistics`

**响应**

- `200` — 成功

### 筛选下拉选项

`GET /api/students/filter-options`

**响应**

- `200` — 成功

### 上报抽签（写操作日志）

`POST /api/students/draw`

抽签结束后记一条日志 权限沿用列表接口的 committee_required。「点一回取一个」在一次会话里可能点 几十下，但那属于同一次抽签 —— 由前端在关闭弹窗时上报一次，这里只收一条。 **日志里不写抽中了谁**，详情只有人数：抽签结果是当场用掉的，把名字留下来 反而成了「谁被抽中过」的名册。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `scope` | string | 是 | 抽取范围：从表格里选 / 男生 / 女生 / 全班 |
| `count` | integer（≥0） | 是 | 本次抽中的人数 |

**响应**

- `200` — 成功

### 当前用户头像（自己的高考照片）

`GET /api/students/me/photo`

u 参数仅用于前端绕过浏览器缓存（切换账号时 URL 不同），后端不使用

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `u` | query | 否 | string |  |

**响应**

- `200` — 成功

### 我的信息（当前登录者自己那条）

`GET /api/students/me`

**响应**

- `200` `StudentResponse` — 成功
  - 字段：`student_no`、`name`、`gender`、`major`、`class_name`、`birth_date`、`ethnicity`、`political_status`、`hometown`、`id_card`、`exam_no`、`exam_category`、`subject_type`、`exam_type`、`admission_batch`、`gaokao_score`、`high_school`、`registration_status`、`registration_time`、`school_status`、`phone`、`family_phone`、`qq`、`email`、`family_address`、`postal_code`、`dormitory`、`bed`、`class_position`、`league_position`、`is_poor`、`remark`、`gaokao_photo`、`on_site_photo`、`id_photo`、`id`、`remark_attachments`

### 指定学生照片

`GET /api/students/{student_id}/photo`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |
| `type` | query | 否 | string | gaokao=高考照片, on_site=实地采集, id=自备证件照 默认 `gaokao` |
| `v` | query | 否 | string |  |

**响应**

- `200` — 成功

### 上传/替换学生照片（仅管理员）

`POST /api/students/{student_id}/photo`

传新照片就换掉旧的；旧文件在提交成功之后才删

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |
| `type` | query | 否 | string | gaokao=高考照片, on_site=实地采集, id=自备证件照 默认 `gaokao` |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 | 照片文件 |

**响应**

- `200` — 成功

### 删除学生照片（仅管理员）

`DELETE /api/students/{student_id}/photo`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |
| `type` | query | 否 | string | gaokao=高考照片, on_site=实地采集, id=自备证件照 默认 `gaokao` |

**响应**

- `200` — 成功

### 学生详情

`GET /api/students/{student_id}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |

**响应**

- `200` `StudentResponse` — 成功
  - 字段：`student_no`、`name`、`gender`、`major`、`class_name`、`birth_date`、`ethnicity`、`political_status`、`hometown`、`id_card`、`exam_no`、`exam_category`、`subject_type`、`exam_type`、`admission_batch`、`gaokao_score`、`high_school`、`registration_status`、`registration_time`、`school_status`、`phone`、`family_phone`、`qq`、`email`、`family_address`、`postal_code`、`dormitory`、`bed`、`class_position`、`league_position`、`is_poor`、`remark`、`gaokao_photo`、`on_site_photo`、`id_photo`、`id`、`remark_attachments`

### 更新学生信息

`PUT /api/students/{student_id}`

管理员可改所有字段；班委只能改备注和附件，其余的字段静静忽略（不是报错） 请求体用 multipart/form-data，原因是备注要支持附件上传： - student_data：JSON 字符串，字段与 StudentUpdate 一致；空串表示只改附件 - remark_new_attachments：本次新增的备注附件（最多 3 个） - remark_keep_attachments：要保留的原附件下标 JSON 数组（空=全部保留）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `student_data` | string | 否 | 学生信息 JSON 字符串 |
| `remark_new_attachments` | string[] | 否 | 备注新增附件，单次最多 3 个 |
| `remark_keep_attachments` | string | 否 | 保留的原备注附件下标（JSON 数组，如 [0,2]） |

**响应**

- `200` `StudentResponse` — 成功
  - 字段：`student_no`、`name`、`gender`、`major`、`class_name`、`birth_date`、`ethnicity`、`political_status`、`hometown`、`id_card`、`exam_no`、`exam_category`、`subject_type`、`exam_type`、`admission_batch`、`gaokao_score`、`high_school`、`registration_status`、`registration_time`、`school_status`、`phone`、`family_phone`、`qq`、`email`、`family_address`、`postal_code`、`dormitory`、`bed`、`class_position`、`league_position`、`is_poor`、`remark`、`gaokao_photo`、`on_site_photo`、`id_photo`、`id`、`remark_attachments`

### 删除学生（仅管理员）

`DELETE /api/students/{student_id}`

删除学生，连同他的登录账号、办件记录和照片文件一起清掉 两道闸： 1. 不能删当前登录的账号 —— 管理员本人也是学生，删了就没人管这个系统了 2. 还有待处理的申请时拒绝（请假 / 信息修改 / 证明开具 / 电动车通行证）—— 否则班委点「通过」会撞上「学生不存在」，那些待办也没法收尾了 已审核过的请假、反馈、修改申请**原样保留**：它们存的是姓名学号的快照， 不依赖学生表，属于历史记录，不该因为删人而消失。 证明和通行证不一样：它们挂的是学生主键、没有姓名快照，留着既查不出是谁开的、 又要撞 NOT NULL 外键，所以跟着学生一起删（见 student_service.delete_student）， 占用的附件和成品文件也一并清掉。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载备注附件

`GET /api/students/{student_id}/remark-attachments/{index}`

按学生 id 和附件下标下载备注附件 权限：班委及以上能看所有人的；普通学生只能看自己的（与备注字段一致）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |
| `index` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 解析 Excel 并预览（仅管理员，不写库）

`POST /api/students/import/preview`

上传 Excel，解析后返回预览统计（不写库、不写照片文件） 返回里带一个 token，确认导入时再传回来。token 对应服务端临时文件，10 分钟过期。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `sheet_name` | query | 否 | string，可空 | 工作表名，留空自动选「全部信息」或第一张 |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 | Excel 文件 |

**响应**

- `200` `ImportPreviewResponse` — 成功
  - 字段：`sheet_name`、`available_sheets`、`total_rows`、`will_create`、`will_update`、`skip_count`、`sample_create`、`sample_update`、`photo_count`、`warnings`、`token`

### 确认导入（仅管理员）

`POST /api/students/import`

根据预览令牌，真正把数据写入数据库 覆盖规则：学号已存在的学生，只更新 students 表字段，不动账号密码/角色/冻结状态/推送订阅。 学号被域外账号占用的行，在预览阶段就跳过了，不会到这里。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `token` | string | 是 | 预览接口返回的令牌 |

**响应**

- `200` `ImportResultResponse` — 成功
  - 字段：`created`、`updated`、`skipped`、`warnings`、`message`

### 解析照片 zip 并预览（仅管理员，不写库）

`POST /api/students/photos/import/preview`

上传 zip，逐张判断这张是谁的照片（不写库、不写文件） 返回里带一个 token，确认导入时连同 photo_type 一起传回来。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `photo_type` | query | 是 | string | gaokao=高考照片, on_site=实地采集, id=自备证件照, sign=签字图 |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 | zip 压缩包 |

**响应**

- `200` `PhotoZipPreviewResponse` — 成功
  - 字段：`token`、`photo_type`、`total`、`counts`、`will_overwrite`、`items`

### 确认导入照片（仅管理员）

`POST /api/students/photos/import`

按预览令牌真正落盘并写库 覆盖与否由这次请求的 overwrite 决定，不在预览阶段定 —— 预览时用户还没做选择。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `token` | string | 是 | 预览接口返回的令牌 |
| `photo_type` | string | 是 | gaokao / on_site / id / sign，与预览时一致 |
| `overwrite` | boolean | 否 | 已有照片也覆盖 |
| `manual` | object | 否 | 人工指认：zip 成员名 → 学号，只对自动认不出的那些有意义 |

**响应**

- `200` `PhotoZipResultResponse` — 成功
  - 字段：`saved`、`overwritten`、`skipped_exists`、`failed`、`message`

### 批量删除学生（仅管理员）

`POST /api/students/batch-delete`

批量删除学生：能删就删，不能删的返回理由 逐条判断，互不影响：删自己、有待处理的申请、学生不存在都算失败。 返回 { success, failed: [{student_no, name, reason}], message }。 历史记录（已审核的请假/反馈/改信息申请）原样保留，跟单条删除一致； 证明/通行证的申请挂的是学生主键、没存姓名快照，留不住，跟着学生一起删 （占用的磁盘文件也一并清掉）。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `ids` | integer[] | 是 | 要删除的学生 id 列表 |

**响应**

- `200` — 成功

## 文件公开

### 文件列表（按发布时间降序）

`GET /api/announcements`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `keyword` | query | 否 | string，可空 | 按标题或文号模糊搜索 |
| `start_date` | query | 否 | string，可空 | 发布时间起始（YYYY-MM-DD） |
| `end_date` | query | 否 | string，可空 | 发布时间截止（YYYY-MM-DD） |

**响应**

- `200` — 成功
  - 字段：AnnouncementResponse[]

### 上传PDF并发布公告（班委及以上）

`POST /api/announcements`

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 文件标题 |
| `doc_number` | string | 否 | 文号 |
| `publish_date` | string | 是 | 发布时间 |
| `is_public` | boolean | 否 | 是否向班委以外公开 |
| `file` | string | 是 | PDF 文件 |

**响应**

- `200` `AnnouncementResponse` — 成功
  - 字段：`id`、`title`、`doc_number`、`publish_date`、`file_path`、`file_name`、`publisher`、`is_public`、`view_count`、`created_at`

### 查看/下载公告文件（需登录）

`GET /api/announcements/file/{file_name}`

按文件名下发 PDF；只取文件名，杜绝路径穿越

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `file_name` | path | 是 | string |  |
| `download` | query | 否 | boolean | true=作为附件下载，false=浏览器内预览 默认 `False` |

**响应**

- `200` — 成功

### 删除公告（班委及以上）

`DELETE /api/announcements/{announcement_id}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `announcement_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

## 资料下载

### 可下载资料清单（需登录）

`GET /api/resources`

按分类分组返回资料列表 返回格式与旧版完全一致，前端 Downloads 页面零改动。

**响应**

- `200` — 成功

### 下载资料文件（需登录）

`GET /api/resources/file/{file_name}`

按文件名下发资料；只取文件名，且必须命中数据库，杜绝越权取任意文件 白名单从数据库读，而不是旧版的 RESOURCE_CATALOG 集合， 这样管理员新加的资料立刻就能下，不用改代码。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `file_name` | path | 是 | string |  |
| `download` | query | 否 | boolean | true=作为附件下载，false=浏览器内预览 默认 `True` |

**响应**

- `200` — 成功

## 关于班级

### 班级概况（人数、性别分布、班委名单）

`GET /api/about`

**响应**

- `200` `AboutResponse` — 成功
  - 字段：`total`、`gender`、`committee`、`version`

## 修改申请

### 申请列表（班委及以上）

`GET /api/change-requests`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string，可空 | pending|approved|rejected，不传为全部 |
| `keyword` | query | 否 | string，可空 | 按提交人姓名或学号模糊搜索 |
| `start` | query | 否 | string，可空 | 提交日期起始，含当天 |
| `end` | query | 否 | string，可空 | 提交日期结束，含当天 |

**响应**

- `200` — 成功
  - 字段：ChangeRequestResponse[]

### 提交信息修改申请

`POST /api/change-requests`

**响应**

- `200` `ChangeRequestResponse` — 成功
  - 字段：`id`、`student_no`、`student_name`、`changes`、`status`、`reason`、`created_at`、`reviewed_at`、`reviewer_name`、`current`

### 我的申请记录

`GET /api/change-requests/me`

**响应**

- `200` — 成功
  - 字段：ChangeRequestResponse[]

### 审核时对照用的照片（班委及以上）

`GET /api/change-requests/{request_id}/photo`

给审核页并排展示「原图 / 新图」用。 新照片在通过之前只躺在这条申请的 changes 里（还没写进学生表）， 所以取不到 —— 拿 GET /api/students/{id}/photo 来取的话，两个方向都是旧图。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `request_id` | path | 是 | integer |  |
| `side` | query | 否 | string | old=学生当前的照片，new=申请里上传的新照片 默认 `new` |

**响应**

- `200` — 成功

### 通过申请

`POST /api/change-requests/{request_id}/approve`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `request_id` | path | 是 | integer |  |

**响应**

- `200` `ChangeRequestResponse` — 成功
  - 字段：`id`、`student_no`、`student_name`、`changes`、`status`、`reason`、`created_at`、`reviewed_at`、`reviewer_name`、`current`

### 驳回申请

`POST /api/change-requests/{request_id}/reject`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `request_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 驳回理由 |

**响应**

- `200` `ChangeRequestResponse` — 成功
  - 字段：`id`、`student_no`、`student_name`、`changes`、`status`、`reason`、`created_at`、`reviewed_at`、`reviewer_name`、`current`

## 请假申请

### 我的请假记录

`GET /api/leaves/my`

当前登录学生自己的请假申请，按时间倒序

**响应**

- `200` — 成功
  - 字段：LeaveRequestResponse[]

### 请假申请列表（班委及以上可见）

`GET /api/leaves`

班委可以看列表和详情，但只有管理员能审批（通过/驳回）和生成 Word `open` 是「待处理」那一档：受理后状态会从 pending 变成 accepted，只看 pending 的话「受理」这个动作看起来像把申请弄丢了，而菜单红点还照数它 —— 所以待办口径 必须是「还没办结且轮到我动手的」，见 services/review_flow.py 的 ADMIN_TODO。 默认档是「全部」：进来先看见所有的，要收窄再自己点

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string，可空 | pending/accepted/correcting/approved/rejected/revoked；open = 待处理（待受理+已受理），closed = 已办结（已通过+已驳回+已撤销），不传为全部 |
| `keyword` | query | 否 | string，可空 | 按提交人姓名或学号模糊搜索 |
| `start` | query | 否 | string，可空 | 提交日期起始，含当天 |
| `end` | query | 否 | string，可空 | 提交日期结束，含当天 |

**响应**

- `200` — 成功
  - 字段：LeaveRequestResponse[]

### 提交请假申请

`POST /api/leaves`

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `leave_type` | string | 是 | 病假/事假/公假 |
| `start_at` | string（日期时间） | 是 | 开始时间，精确到小时 |
| `end_at` | string（日期时间） | 是 | 结束时间，精确到小时 |
| `reason` | string | 是 | 请假事由 |
| `travel_mode` | string | 否 |  |
| `travel_detail` | string | 否 |  |
| `destination` | string | 否 |  |
| `destination_phone` | string | 否 |  |
| `proof` | string | 是 | 请假辅助证明（图片或 PDF，必填） |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 修改请假申请（未办结时）

`PUT /api/leaves/{leave_id}`

申请人自己改：待受理、待补正这两种状态能改，其余一律 400 字段是**整套覆盖**，跟重新提交一次一样 —— 少传一个就等于清空它，所以前端 编辑时必须把原值都带上。 改完的落点分两种（见 review_flow.resubmit）：原本待补正的回到「已受理」—— 待补正也算已受理，受理没被撤销，只是材料要补齐，补完不必让班委再看一遍； 原本待受理的仍是待受理，它本来就还没人看过。补正后重交也走这里，不必另开接口。 **不发通知**：这条申请从头到尾都在管理员的「待处理」列表里（open 档含这两档状态）， 不需要再喊一声。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `leave_type` | string | 是 | 病假/事假/公假 |
| `start_at` | string（日期时间） | 是 | 开始时间，精确到小时 |
| `end_at` | string（日期时间） | 是 | 结束时间，精确到小时 |
| `reason` | string | 是 | 请假事由 |
| `travel_mode` | string | 否 |  |
| `travel_detail` | string | 否 |  |
| `destination` | string | 否 |  |
| `destination_phone` | string | 否 |  |
| `proof` | string，可空 | 否 |  |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 撤销请假申请（待受理时）

`DELETE /api/leaves/{leave_id}`

申请人自己撤：**只有「待受理」能撤**，直接删掉记录和盘上的证明材料 已受理的不给撤（那是班委看过、正在走流程的单子，要撤得先让班委撤回受理）； 待补正的不给撤（是让补材料，不是让放弃，真不想办了跟班委说一声）。 撤销**不留档、不通知**：撤回一条自己刚交的东西，不需要惊动谁。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 查看/下载我的请假证明

`GET /api/leaves/{leave_id}/proof`

学生只能看自己的证明文件

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载请假审批表 PDF（申请人本人或管理员）

`GET /api/leaves/{leave_id}/pdf`

只有审核通过的申请才能生成表；申请人本人和管理员下到的是**同一份**文件 学生端那个「下载请假表」按钮就在走这条接口 —— 以前它是 admin_required， 学生点下去必定 403，是个死按钮（见 LeaveApply.vue）。 表里的水印用来溯源「谁下载的」，需要下载人是谁，所以不再用 admin_required 那种 只认角色的依赖，改成拿当前账号自己比对。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载请假证明文件（班委及以上）

`GET /api/leaves/{leave_id}/proof/admin`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 受理请假申请

`POST /api/leaves/{leave_id}/accept`

受理：这份材料看过了，可以进入审批 前端在管理员打开证明材料时顺手发一个，另有一个「受理」按钮兜底（材料文件丢了、 或者根本没附件的单子，只看是受理不了的）。已经受理过的原样返回（幂等）—— 反复打开材料不该报错。 **不发通知**（用户口径）：受理只是审批人自己的一步，学生那边只看到状态变了； 受理也不碰 reviewer_no / reviewed_at —— 那是审批结果的一部分，记上去会让这条 申请提前出现在「我审批的」里。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 撤回受理

`POST /api/leaves/{leave_id}/unaccept`

受理点错了的回头路：已受理 → 待受理 只退受理，不动审批结果 —— 但已办结（通过/驳回）的单子本来就退不回来：审批一旦 发出（通知已推送、PDF 已生成、签字图已快照），静默改写等于篡改已发出的正式单据 （与「补签字不重审」同一条口径）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 退回补正

`POST /api/leaves/{leave_id}/correcting`

材料不对，打回让申请人补齐（带理由，申请人看得见） 和驳回分开：驳回是「这件事不批了」，补正是「补齐了还能批」。学生改完重交会回到 「已受理」—— 受理没被撤销，不必让班委再看一遍。 退回补正**要发通知**：这是一句需要学生动手的交代，不喊一声他不会知道材料被退回来了。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 要补什么材料 |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 能当班导师签字人的账号（管理员）

`GET /api/leaves/advisor-signers`

列管理员、且签字图在盘上的账号，供批准时选「用谁的签字」 口径与电动车那份（GET /api/ev-passes/signers）共用，见 services/signer_service.py

**响应**

- `200` — 成功

### 通过请假申请

`POST /api/leaves/{leave_id}/approve`

批准时可顺带填班导师意见、选一个管理员的签字（两者都选填） body 整个是可选的：老前端那句 `approveLeave(id)` 不带 body 也得照样能用。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

类型：LeaveAdvisorSignature，可空

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 撤销已通过的请假申请

`POST /api/leaves/{leave_id}/revoke`

管理员把一条已通过的申请撤了：状态变成「已撤销」，学生端不再显示审核意见 撤销后这条单子不能再编辑、不再生成审批表（下载接口按状态拦）；它也不再能批、 不能补签字 —— **撤销是终态，没有反向操作**。 要发通知：申请人手里的表可能已经打印出去了，不喊一声他不会知道这张表作废了。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 补签字（批准时选了「暂不签字」之后）

`POST /api/leaves/{leave_id}/advisor-sign`

给一条已批准、当初没签字的请假记录补上签字 单独开一个接口、而不是「再批一次」，是为了不碰 status / reviewer / 审核时间 —— 补的是签字，不是重新审一遍。意见也顺带收，那时候没填的可以一起补上。 **已经签过的一律 400**：快照语义下静默改写等于篡改已经发出去的那张表。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `advisor_opinion` | string | 否 | 班导师意见（选填） |
| `advisor_sign_no` | string | 否 | 签字人的登录名，空串 = 暂不签字 |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

### 驳回请假申请

`POST /api/leaves/{leave_id}/reject`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `leave_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 驳回理由 |

**响应**

- `200` `LeaveRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`leave_type`、`start_at`、`end_at`、`reason`、`travel_mode`、`travel_detail`、`destination`、`destination_phone`、`proof_original_name`、`status`、`reviewer_name`、`reject_reason`、`correction_reason`、`created_at`、`reviewed_at`、`advisor_opinion`、`advisor_sign_no`、`advisor_sign_name`、`has_advisor_sign`

## 考勤记录

### 导出考勤记录（班委及以上）

`GET /api/attendance/export`

点开导出必须同时拿到点名与签到两种记录，各占一个工作表。 两种导出方式： - 传了 `record_ids` / `checkin_ids`：只导勾选的记录（另一个页签就空着）； - 没传：按日期与关键词导出「当前筛选结果」，关键词对点名查备注、 对签到查标题，和列表页的口径完全一致。 签到结算出来的那几条本来就在「考勤记录」里（和点名记录同表）， 这里再单列一张「签到记录」，把本人签到时间、距离和请假情况也带上， 核对时不用两个页签来回翻。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `start` | query | 否 | string，可空 | 起始日期，含当天 |
| `end` | query | 否 | string，可空 | 结束日期，含当天 |
| `keyword` | query | 否 | string，可空 | 按点名备注或签到标题模糊搜索 |
| `record_ids` | query | 否 | integer[] | 只导出选中的点名记录 |
| `checkin_ids` | query | 否 | integer[] | 只导出选中的签到 |

**响应**

- `200` — 成功

### 点名与签到记录汇总（班委及以上）

`GET /api/attendance/overview`

点名与签到合成一张列表，按时间倒序排 关键词对点名查备注、对签到查标题 —— 两边能用来认出这次记录的那句话 不是同一个字段，但都是用户记得住的那句。两类数据量都是班级级， 合并后在内存里排序、分页就够了，不必依赖 UNION。 签到结算后不再新冒出一条「点名」行：这次签到本身那一行直接换成 标准格式的人数字段，一次签到始终只占一行。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `start` | query | 否 | string，可空 | 起始日期，含当天 |
| `end` | query | 否 | string，可空 | 结束日期，含当天 |
| `keyword` | query | 否 | string，可空 | 按点名备注或签到标题模糊搜索 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `AttendanceOverviewResponse` — 成功
  - 字段：`total`、`items`

### 批量删除点名与签到记录（班委及以上）

`POST /api/attendance/batch-delete`

一次删掉勾选的记录。 - 签到：连它的 targets、照片、结算生成的考勤一起删，链接随即失效； - 点名：连明细一起删； - 勾了签到生成的考勤却没勾那次签到：把身后的签到也一起删， 否则会留下指空的签到，那条考勤也会变成删不得的历史记录。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `record_ids` | integer[] | 否 | 考勤记录 id |
| `checkin_ids` | integer[] | 否 | 签到 id |

**响应**

- `200` — 成功

### 考勤记录列表（班委及以上）

`GET /api/attendance`

列表只带聚合计数，不带明细（明细走 GET /{record_id}）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `start` | query | 否 | string，可空 | 起始日期，含当天 |
| `end` | query | 否 | string，可空 | 结束日期，含当天 |
| `keyword` | query | 否 | string，可空 | 按备注模糊搜索 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `AttendanceListResponse` — 成功
  - 字段：`total`、`items`

### 上报一次点名（班委及以上）

`POST /api/attendance`

点名结束后把每个人的状态落库 权限沿用列表接口的 committee_required：看得到名单的人才点得了名。 同时写一条操作日志（action=点名）—— 「谁在什么时候点了谁的名」这件事 仍然是操作日志的价值所在，只是现在明细也有地方存了。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `scope` | string | 是 | 点名范围：全班 / 男生 / 女生 / 共青团员 |
| `records` | AttendanceItemIn[] | 是 | 被点到的每个人 |

`records` 的字段：

  - `student_no`：string（必填）
  - `name`：string
  - `status`：string（必填）

**响应**

- `200` `AttendanceRecordResponse` — 成功
  - 字段：`id`、`call_date`、`scope`、`called_at`、`operator_no`、`operator_name`、`remark`、`total`、`present`、`leave`、`absent`、`items`

### 考勤详情（班委及以上）

`GET /api/attendance/{record_id}`

带明细，供「查看明细 / 改状态」的对话框用

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `record_id` | path | 是 | integer |  |

**响应**

- `200` `AttendanceRecordResponse` — 成功
  - 字段：`id`、`call_date`、`scope`、`called_at`、`operator_no`、`operator_name`、`remark`、`total`、`present`、`leave`、`absent`、`items`

### 写某次点名的备注（班委及以上）

`PATCH /api/attendance/{record_id}`

给这一次点名补一句话说明，例如「学院临时集合，迟到 5 人」。 整条替换、传空即清掉，所以不另开「删除备注」的接口。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `record_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remark` | string | 否 | 备注，空串表示清掉 |

**响应**

- `200` `AttendanceRecordResponse` — 成功
  - 字段：`id`、`call_date`、`scope`、`called_at`、`operator_no`、`operator_name`、`remark`、`total`、`present`、`leave`、`absent`、`items`

### 删除一条考勤记录（班委及以上）

`DELETE /api/attendance/{record_id}`

整条删掉（含明细）。点错范围、重复上报时用

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `record_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 改某人状态（班委及以上）

`PATCH /api/attendance/{record_id}/items/{student_no}`

当场点名难免点错，事后要能改回来

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `record_id` | path | 是 | integer |  |
| `student_no` | path | 是 | string |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 是 |  |

**响应**

- `200` `AttendanceRecordResponse` — 成功
  - 字段：`id`、`call_date`、`scope`、`called_at`、`operator_no`、`operator_name`、`remark`、`total`、`present`、`leave`、`absent`、`items`

## 签到

### 签到列表（班委及以上）

`GET /api/checkins`

**响应**

- `200` `CheckinListResponse` — 成功
  - 字段：`total`、`items`

### 发布签到（班委及以上）

`POST /api/checkins`

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 标题 |
| `remark` | string | 否 | 备注，空串 = 没写 |
| `targets` | string[] | 是 | 范围内学生的学号 |
| `start_at` | string（日期时间），可空 | 否 | 开始时间，为空 = 发布即可签 |
| `end_at` | string（日期时间） | 是 | 截止时间 |
| `require_photo` | boolean | 否 | 是否要求上传一张照片 |
| `location` | CheckinLocationIn，可空 | 否 |  |

**响应**

- `200` `CheckinDetailResponse` — 成功
  - 字段：`id`、`code`、`title`、`status`、`created_by_name`、`created_at`、`start_at`、`end_at`、`target_count`、`signed_count`、`link`、`remark`、`require_photo`、`location`、`created_by_no`、`closed_at`、`finalized_at`、`attendance_record_id`、`targets`

### 签到公开信息（凭链接，无需登录）

`GET /api/checkins/public/{code}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `code` | path | 是 | string |  |

**响应**

- `200` `CheckinPublicResponse` — 成功
  - 字段：`code`、`title`、`remark`、`status`、`created_by_name`、`created_at`、`start_at`、`end_at`、`require_photo`、`location`、`target_count`、`link`、`is_login`、`is_target`、`can_sign`、`grace_until`、`signed_at`、`my_distance_m`、`on_leave`

### 提前结束签到（班委及以上）

`POST /api/checkins/{checkin_id}/close`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `checkin_id` | path | 是 | integer |  |

**响应**

- `200` `CheckinDetailResponse` — 成功
  - 字段：`id`、`code`、`title`、`status`、`created_by_name`、`created_at`、`start_at`、`end_at`、`target_count`、`signed_count`、`link`、`remark`、`require_photo`、`location`、`created_by_no`、`closed_at`、`finalized_at`、`attendance_record_id`、`targets`

### 延长签到截止时间 5 分钟（班委及以上）

`POST /api/checkins/{checkin_id}/extend`

截止前可反复延长，每次 5 分钟，不设上限。 只能在本来的截止时间到之前操作：已经到点（哪怕还没懒结算）就不算了， 否则会把一次已经结束的签到重新拉回进行中，和结算结果对不上。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `checkin_id` | path | 是 | integer |  |

**响应**

- `200` `CheckinDetailResponse` — 成功
  - 字段：`id`、`code`、`title`、`status`、`created_by_name`、`created_at`、`start_at`、`end_at`、`target_count`、`signed_count`、`link`、`remark`、`require_photo`、`location`、`created_by_no`、`closed_at`、`finalized_at`、`attendance_record_id`、`targets`

### 提醒还没签到的同学（班委及以上）

`POST /api/checkins/{checkin_id}/remind`

只给还没签到的人发站内信，已签的、范围外的人都不打扰。 和发布时一样，notify 自己会 commit，必须放在这次请求的事务 commit 之后。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `checkin_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 签到详情（班委及以上）

`GET /api/checkins/{checkin_id}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `checkin_id` | path | 是 | integer |  |

**响应**

- `200` `CheckinDetailResponse` — 成功
  - 字段：`id`、`code`、`title`、`status`、`created_by_name`、`created_at`、`start_at`、`end_at`、`target_count`、`signed_count`、`link`、`remark`、`require_photo`、`location`、`created_by_no`、`closed_at`、`finalized_at`、`attendance_record_id`、`targets`

### 改签到标题（班委及以上）

`PATCH /api/checkins/{checkin_id}`

列表的「备注」列显示的、关键词搜索搜的，都是这里改的标题。 标题不能清空：空标题在列表里认不出是哪次签到，也没法搜。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `checkin_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 签到标题，不能为空 |

**响应**

- `200` `CheckinDetailResponse` — 成功
  - 字段：`id`、`code`、`title`、`status`、`created_by_name`、`created_at`、`start_at`、`end_at`、`target_count`、`signed_count`、`link`、`remark`、`require_photo`、`location`、`created_by_no`、`closed_at`、`finalized_at`、`attendance_record_id`、`targets`

### 删除一次签到（班委及以上）

`DELETE /api/checkins/{checkin_id}`

删掉签到本身、签到照片，以及结算时生成的那条考勤记录。 反过来，在考勤列表里删那条生成的考勤也会连这次签到一起删 （见 attendance.delete_attendance），两边都不留指空的数据。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `checkin_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 查看签到照片（班委及以上）

`GET /api/checkins/{checkin_id}/targets/{student_no}/photo`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `checkin_id` | path | 是 | integer |  |
| `student_no` | path | 是 | string |  |

**响应**

- `200` — 成功

### 先上传签到照片（需登录且在范围内）

`POST /api/checkins/public/{code}/photo`

选中照片就传上来，不等点「签到」。 **不能**把文件声明成 `File(...)` 参数：FastAPI 会先收完整个请求体才进函数， 那样记下的是「传完」时间。这里一进函数就先取时间，作为上传开始时间签进 令牌；截止前开始传的，哪怕传完已经过点，签到接口也会认。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `code` | path | 是 | string |  |

**响应**

- `200` — 成功

### 学生签到（需登录且在范围内）

`POST /api/checkins/public/{code}/sign`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `code` | path | 是 | string |  |

**请求体**（`application/x-www-form-urlencoded`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `lat` | number，可空 | 否 | GCJ-02 纬度 |
| `lng` | number，可空 | 否 | GCJ-02 经度 |
| `photo_token` | string，可空 | 否 | 先上传照片拿到的令牌 |

**响应**

- `200` `CheckinPublicResponse` — 成功
  - 字段：`code`、`title`、`remark`、`status`、`created_by_name`、`created_at`、`start_at`、`end_at`、`require_photo`、`location`、`target_count`、`link`、`is_login`、`is_target`、`can_sign`、`grace_until`、`signed_at`、`my_distance_m`、`on_leave`

## 意见反馈

### 我的反馈

`GET /api/feedback/my`

当前登录学生自己的反馈列表，按时间倒序

**响应**

- `200` — 成功
  - 字段：FeedbackResponse[]

### 反馈列表（班委及以上）

`GET /api/feedback`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string，可空 | unread/read/replied，不传为全部 |
| `keyword` | query | 否 | string，可空 | 按提交人姓名或学号模糊搜索 |
| `start` | query | 否 | string，可空 | 提交日期起始，含当天 |
| `end` | query | 否 | string，可空 | 提交日期结束，含当天 |

**响应**

- `200` — 成功
  - 字段：FeedbackResponse[]

### 提交意见反馈

`POST /api/feedback`

提交反馈（multipart：正文和附件一起发） 附件条数上限没用注解表达，因为超限时 FastAPI 抛的是 422、detail 是 list of dict，前端弹出来是 [object Object]。手写 400 + 中文原因更好排查。 另一个会抛 422 的地方：multipart 里 filename 为空串的 part 会被 FastAPI 当成普通字段（Expected UploadFile, received: str），而且是在进这个函数 之前就整单拒掉，这里接不住。el-upload 只会送用户真实选中的 File （一定有名字），正常路径碰不到，所以不为此加防御。

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 标题 |
| `content` | string | 是 | 正文 |
| `attachments` | string[] | 否 | 附件，最多 3 个 |

**响应**

- `200` `FeedbackResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`title`、`content`、`status`、`attachments`、`reply_content`、`reply_name`、`reply_no`、`reply_at`、`created_at`

### 查看我的反馈详情

`GET /api/feedback/{feedback_id}`

学生只能看自己的

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `feedback_id` | path | 是 | integer |  |

**响应**

- `200` `FeedbackResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`title`、`content`、`status`、`attachments`、`reply_content`、`reply_name`、`reply_no`、`reply_at`、`created_at`

### 下载反馈附件

`GET /api/feedback/{feedback_id}/attachments/{index}`

班委及以上能下任意反馈的附件，普通学生只能下自己那条 越权时用 404 而不是 403：不泄露「这条反馈存在，只是不属于你」 （同 my_feedback_detail 的处理）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `feedback_id` | path | 是 | integer |  |
| `index` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 反馈详情（班委）

`GET /api/feedback/{feedback_id}/detail`

班委查看详情。如果状态是 unread，自动标记为已读。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `feedback_id` | path | 是 | integer |  |

**响应**

- `200` `FeedbackResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`title`、`content`、`status`、`attachments`、`reply_content`、`reply_name`、`reply_no`、`reply_at`、`created_at`

### 标记已读（班委）

`POST /api/feedback/{feedback_id}/mark-read`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `feedback_id` | path | 是 | integer |  |

**响应**

- `200` `FeedbackResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`title`、`content`、`status`、`attachments`、`reply_content`、`reply_name`、`reply_no`、`reply_at`、`created_at`

### 回复反馈（班委）

`POST /api/feedback/{feedback_id}/reply`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `feedback_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `content` | string | 是 | 回复内容 |

**响应**

- `200` `FeedbackResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`title`、`content`、`status`、`attachments`、`reply_content`、`reply_name`、`reply_no`、`reply_at`、`created_at`

## 未读红点

### 菜单红点计数

`GET /api/badges`

返回 {"notice_unread": 通知未读数, "inbox_unread": 站内信未读数, "review_tabs": 各分类待办数, "review_pending": 待办合计} notice_unread 和 inbox_unread 是两回事，不合并：前者数的是「通知公告里有几篇 没看」，点进去是文章列表；后者数的是「收件箱里几条没看」，点进去是消息流水。 同一条通知在这两处各算一次是有意的 —— 一个页面一个口径。 review_tabs 的键就是审核页的 tab 名，审核页每个 tab 上各显示自己那个数字。 leave / evpass / export / certificate / signphoto **只给管理员算**：这几类只有管理员能批 （leaves.py、ev_passes.py、exports.py、certificates.py、sign_photos.py 的 approve/reject 都是 admin_required），给班委也算上的话， 红点数字虚高、点进去却批不了。 三个办件（leave / evpass / certificate）数的是 **ADMIN_TODO**（待受理 + 已受理）， 不是单单一档 pending：办件多了「受理」这一步，受理后状态就变成 accepted 了， 只数 pending 的话管理员一受理，红点当场减一、而这件事其实还等着他批。 这个口径和审核页「待处理」那一档（列表接口的 status=open）、 以及「删学生时的未办结拦截」同源，见 services/review_flow.py。 review_pending 是 review_tabs 的和，不再单独算一遍 —— 菜单上的数字和 点进去各 tab 的数字同源，不会出现「菜单显示 3、每个 tab 都是 0」这种对不上的情况。 这些计数直接 COUNT 出数，不走各家的列表接口 —— 那些列表都没有分页、 一次返回全部行，为了拿一个数字拉全表不划算。

**响应**

- `200` — 成功

## 电动车通行证

### 我的电动车通行证申请

`GET /api/ev-passes/my`

当前登录学生的所有申请，按时间倒序

**响应**

- `200` — 成功
  - 字段：EvPassRequestResponse[]

### 电动车通行证申请列表（班委及以上）

`GET /api/ev-passes`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string，可空 | 按状态筛选：pending/accepted/correcting/approved/rejected/revoked；open = 待处理（待受理+已受理），closed = 已办结（已通过+已驳回+已撤销） |
| `keyword` | query | 否 | string，可空 | 按提交人姓名或学号模糊搜索 |
| `start` | query | 否 | string，可空 | 提交日期起始，含当天 |
| `end` | query | 否 | string，可空 | 提交日期结束，含当天 |

**响应**

- `200` — 成功
  - 字段：EvPassRequestResponse[]

### 提交电动车通行证申请

`POST /api/ev-passes`

学生提交补办申请（multipart form）

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `brand` | string | 是 | 电动车品牌 |
| `plate_number` | string | 是 | 车牌号 |
| `license_file` | string | 是 | 行驶证照片（图片或 PDF） |

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 查看我的行驶证

`GET /api/ev-passes/{req_id}/license`

学生查看自己的行驶证

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 修改申请（未办结时）

`PUT /api/ev-passes/{req_id}`

申请人自己改：待受理、待补正这两种状态能改，其余一律 400 字段是**整套覆盖**，跟重新提交一次一样 —— 少传一个就等于清空它，所以前端 编辑时必须把原值都带上。 改完的落点分两种（见 review_flow.resubmit）：原本待补正的回到「已受理」—— 待补正也算已受理，受理没被撤销，只是材料要补齐，补完不必让班委再看一遍； 原本待受理的仍是待受理，它本来就还没人看过。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `brand` | string | 是 | 电动车品牌 |
| `plate_number` | string | 是 | 车牌号 |
| `license_file` | string，可空 | 否 |  |

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 撤销申请（待受理时）

`DELETE /api/ev-passes/{req_id}`

申请人自己撤：**只有「待受理」能撤**，直接删掉记录和盘上的行驶证 已受理的不给撤（那是班委看过、正在走流程的单子，要撤得先让班委撤回受理）； 待补正的不给撤（是让补材料，不是让放弃，真不想办了跟班委说一声）。 撤销**不留档、不通知**：撤回一条自己刚交的东西，不需要惊动谁。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载电动车通行证申请表 PDF

`GET /api/ev-passes/{req_id}/pass-pdf`

下载申请表：本人或班委及以上，且仅已通过的可下载 经办班委那一行的签字取**批准当时**存下的那张副本（见 _save_committee_signature）—— 原图后来换了或删了，都不该让这张表掉签字。没签字就不加那一行。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载电动车使用承诺书 PDF

`GET /api/ev-passes/{req_id}/promise-pdf`

下载承诺书：本人或班委及以上，且仅已通过的可下载 「本人签字：」那行印**学生本人**的签字图（申请里传过才有，没传就留一条空下划线手签）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 受理申请（管理员）

`POST /api/ev-passes/{req_id}/accept`

受理：这份材料看过了，可以进入审批 前端在管理员打开行驶证时顺手发一个，另有一个「受理」按钮兜底（没附件的单子 只看是受理不了的）。已经受理过的原样返回（幂等）—— 反复打开材料不该报错。 **不发通知**（用户口径）：受理只是审批人自己的一步，学生那边只看到状态变了； 也不碰 reviewer_no / reviewed_at —— 那是审批结果的一部分。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 撤回受理（管理员）

`POST /api/ev-passes/{req_id}/unaccept`

受理点错了的回头路：已受理 → 待受理 只退受理，不动审批结果 —— 已办结（通过/驳回）的单子本来就退不回来：审批一旦 发出（通知已推送、PDF 已生成、签字图已快照），静默改写等于篡改已发出的正式单据 （与「补签字不重审」同一条口径）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 退回补正（管理员）

`POST /api/ev-passes/{req_id}/correcting`

材料不对，打回让申请人补齐（带理由，申请人看得见） 和驳回分开：驳回是「这件事不批了」，补正是「补齐了还能批」。学生改完重交会回到 「已受理」—— 受理没被撤销，不必让班委再看一遍。 退回补正**要发通知**：这是一句需要学生动手的交代，不喊一声他不会知道材料被退回来了。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 要补什么材料 |

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 通过申请（管理员）

`POST /api/ev-passes/{req_id}/approve`

批准时可顺带选一位管理员的签字（或「暂不签署」） body 整个是可选的：老前端那句 `approveEvPass(id)` 不带 body 也得照样能用。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

类型：EvPassSignature，可空

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 撤销已通过的申请（管理员）

`POST /api/ev-passes/{req_id}/revoke`

把一条已通过的申请撤了：状态变成「已撤销」，申请人不能再编辑、不再提供两份 PDF **撤销是终态，没有反向操作**：撤销后它也不能再批、不能补签字。 要发通知 —— 申请人手里可能已经打印出来了，不喊一声不会知道作废了。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 补签字（批准时选了「暂不签署」之后）

`POST /api/ev-passes/{req_id}/sign`

给一条已批准、当初没签字的申请补上经办班委签字 单独开一个接口、而不是「再批一次」，是为了不碰 status / reviewer / 审核时间 —— 补的是签字，不是重新审一遍。 **已经签过的一律 400**：快照语义下静默改写等于篡改已经发出去的那张表。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `sign_no` | string | 否 | 签字人登录名，空串=暂不签署 |

**响应**

- `200` `EvPassRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`brand`、`plate_number`、`license_original_name`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`sign_name`、`has_sign`

### 能当经办班委签字人的账号（管理员）

`GET /api/ev-passes/signers`

列管理员、且签字图在盘上的账号，供批准时选「用谁的签字」 口径与请假的 GET /api/leaves/advisor-signers 共用（见 services/signer_service.py）。 接口名不叫 advisor-signers：这边签字的是经办班委，落在落款处，不是班导师

**响应**

- `200` — 成功

### 驳回申请（管理员）

`POST /api/ev-passes/{req_id}/reject`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 驳回理由 |

**响应**

- `200` — 成功

### 查看行驶证（班委及以上）

`GET /api/ev-passes/{req_id}/license/admin`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

## 学生信息导出

### 导出字段分组（前端渲染用）

`GET /api/export-requests/field-groups`

**响应**

- `200` — 成功

### 导出申请列表

`GET /api/export-requests`

班委能看全部申请列表（只读），管理员能审批。 班委也能看别人的申请（姓名和类型），这样大家知道导出申请的进度， 但只有自己的能下载（下载接口另外做权限控制）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string | 按状态筛选，空=全部 |
| `keyword` | query | 否 | string，可空 | 按提交人姓名或学号模糊搜索 |
| `start` | query | 否 | string，可空 | 提交日期起始，含当天 |
| `end` | query | 否 | string，可空 | 提交日期结束，含当天 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `ExportRequestListResponse` — 成功
  - 字段：`total`、`items`

### 提交导出申请

`POST /api/export-requests`

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `export_type` | string | 是 | 导出类型：excel_list / pdf_individual |
| `scope_type` | string | 是 | 范围类型：all / filtered / selected / id_range |
| `scope_param` | object，可空 | 否 | 范围参数（JSON） |
| `fields` | string[]，可空 | 否 | 导出字段列表（Excel 用） |

**响应**

- `200` `ExportRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`export_type`、`scope_type`、`scope_param`、`fields`、`file_original_name`、`status`、`reviewer_name`、`reviewer_no`、`reject_reason`、`reviewed_at`、`error_msg`、`created_at`

### 我的导出申请

`GET /api/export-requests/mine`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `ExportRequestListResponse` — 成功
  - 字段：`total`、`items`

### 下载已通过的导出文件

`GET /api/export-requests/{req_id}/download`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 通过导出申请

`POST /api/export-requests/{req_id}/approve`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` `ExportRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`export_type`、`scope_type`、`scope_param`、`fields`、`file_original_name`、`status`、`reviewer_name`、`reviewer_no`、`reject_reason`、`reviewed_at`、`error_msg`、`created_at`

### 驳回导出申请

`POST /api/export-requests/{req_id}/reject`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 驳回理由 |

**响应**

- `200` `ExportRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`export_type`、`scope_type`、`scope_param`、`fields`、`file_original_name`、`status`、`reviewer_name`、`reviewer_no`、`reject_reason`、`reviewed_at`、`error_msg`、`created_at`

## 证明开具

### 我的证明申请

`GET /api/certificates/my`

当前登录学生的所有申请，按时间倒序

**响应**

- `200` — 成功
  - 字段：CertificateRequestResponse[]

### 证明申请列表（班委及以上）

`GET /api/certificates`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string，可空 | 按状态筛选：pending/accepted/correcting/approved/rejected/revoked；open = 待处理（待受理+已受理），closed = 已办结（已通过+已驳回+已撤销） |
| `keyword` | query | 否 | string，可空 | 按提交人姓名或学号模糊搜索 |
| `start` | query | 否 | string，可空 | 提交日期起始，含当天 |
| `end` | query | 否 | string，可空 | 提交日期结束，含当天 |

**响应**

- `200` — 成功
  - 字段：CertificateRequestResponse[]

### 提交证明开具申请

`POST /api/certificates`

学生提交证明开具申请（multipart form）

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 证明标题 |
| `recipient` | string | 否 | 收文单位 |
| `content` | string | 否 | 证明正文 |
| `extra_request` | string | 否 | 其他要求 |
| `attachments` | string[] | 否 | 申请依据附件，最多 3 个 |
| `confirmed` | boolean | 否 | 是否确认信息真实并已联系班委 |

**响应**

- `200` `CertificateRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`title`、`recipient`、`content`、`extra_request`、`attachments`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`result_original_name`

### 查看我的申请附件

`GET /api/certificates/{req_id}/attachment/{index}`

学生查看自己提交的附件

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |
| `index` | path | 是 | integer（≥0） | 附件下标 |

**响应**

- `200` — 成功

### 修改证明申请（未办结时）

`PUT /api/certificates/{req_id}`

申请人自己改：待受理、待补正这两种状态能改，其余一律 400 字段是**整套覆盖**，跟重新提交一次一样 —— 少传一个就等于清空它，所以前端 编辑时必须把原值都带上。 改完的落点分两种（见 review_flow.resubmit）：原本待补正的回到「已受理」—— 待补正也算已受理，受理没被撤销，只是材料要补齐，补完不必让班委再看一遍； 原本待受理的仍是待受理，它本来就还没人看过。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 证明标题 |
| `recipient` | string | 否 | 收文单位 |
| `content` | string | 否 | 证明正文 |
| `extra_request` | string | 否 | 其他要求 |
| `attachments` | string[]，可空 | 否 |  |

**响应**

- `200` `CertificateRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_name`、`student_no`、`title`、`recipient`、`content`、`extra_request`、`attachments`、`status`、`created_at`、`reviewer_name`、`reviewed_at`、`reject_reason`、`correction_reason`、`result_original_name`

### 撤销证明申请（待受理时）

`DELETE /api/certificates/{req_id}`

申请人自己撤：**只有「待受理」能撤**，直接删掉记录和盘上的附件 已受理的不给撤（那是班委看过、正在走流程的单子，要撤得先让班委撤回受理）； 待补正的不给撤（是让补材料，不是让放弃，真不想办了跟班委说一声）。 撤销**不留档、不通知**：撤回一条自己刚交的东西，不需要惊动谁。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载成品证明 PDF（本人）

`GET /api/certificates/{req_id}/result`

学生下载自己申请的成品 PDF（仅已通过状态）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 上传成品证明 PDF（管理员）

`POST /api/certificates/{req_id}/result`

管理员上传成品证明 PDF。申请须已通过，覆盖已有的成品文件。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 | 成品 PDF |

**响应**

- `200` — 成功

### 查看申请附件（班委及以上）

`GET /api/certificates/{req_id}/attachment/{index}/admin`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |
| `index` | path | 是 | integer（≥0） | 附件下标 |

**响应**

- `200` — 成功

### 受理申请（管理员）

`POST /api/certificates/{req_id}/accept`

受理：这份材料看过了，可以进入审批 前端在管理员打开附件时顺手发一个，另有一个「受理」按钮兜底 —— 证明的附件是 **可选**的，一条没带附件的申请没有「打开材料」这个动作，只靠自动受理会永久卡死。 已经受理过的原样返回（幂等）。 **不发通知**（用户口径）：受理只是审批人自己的一步，学生那边只看到状态变了； 也不碰 reviewer_no / reviewed_at —— 那是审批结果的一部分。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 撤回受理（管理员）

`POST /api/certificates/{req_id}/unaccept`

受理点错了的回头路：已受理 → 待受理 只退受理，不动审批结果 —— 已办结（通过/驳回）的单子本来就退不回来：审批一旦 发出（通知已推送、成品 PDF 已上传），静默改写等于篡改已发出的正式单据 （与「补签字不重审」同一条口径）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 退回补正（管理员）

`POST /api/certificates/{req_id}/correcting`

材料不对，打回让申请人补齐（带理由，申请人看得见） 和驳回分开：驳回是「这件事不批了」，补正是「补齐了还能批」。学生改完重交会回到 「已受理」—— 受理没被撤销，不必让班委再看一遍。 退回补正**要发通知**：这是一句需要学生动手的交代，不喊一声他不会知道材料被退回来了。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 要补什么材料 |

**响应**

- `200` — 成功

### 通过申请（管理员）

`POST /api/certificates/{req_id}/approve`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 驳回申请（管理员）

`POST /api/certificates/{req_id}/reject`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 驳回理由 |

**响应**

- `200` — 成功

### 撤销已通过的申请（管理员）

`POST /api/certificates/{req_id}/revoke`

把一条已通过的申请撤了：状态变成「已撤销」，申请人不能再编辑、不再下载成品 **撤销是终态，没有反向操作**：撤销后它也不能再批，成品也不能再上传（上传接口 要求已通过）。要发通知 —— 申请人可能已经拿到打印件，不喊一声不会知道作废了。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 下载成品证明 PDF（管理员）

`GET /api/certificates/{req_id}/result/admin`

管理员下载成品 PDF。班委不可下（用 admin_required 锁住）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `req_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

## 办件空间

### 我申请的办件

`GET /api/workspace/submitted`

当前用户提交过的所有办件，按提交时间倒序。

**响应**

- `200` — 成功
  - 字段：object[]

### 我参与处理的办件

`GET /api/workspace/involved`

我已经有过初步应对的办件（不含纯待办）。 判定口径： - 有 reviewer_no == 我的（我审核过的修改/请假/通行证/证明/导出） - 有 reply_no == 我的（我回复过的反馈） - 反馈的「已读」状态不记录操作人，因此只展示我**回复**过的反馈

**响应**

- `200` — 成功
  - 字段：object[]

## 站内信

### 我的站内信

`GET /api/inbox`

按时间倒序分页；unread 是全量未读数（见 schema 里的说明）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `InboxListResponse` — 成功
  - 字段：`total`、`page`、`page_size`、`unread`、`items`

### 标记一条为已读

`POST /api/inbox/{message_id}/read`

重复调用无副作用（前端点开就调，刷新后再点一次也不报错） 不是自己的消息按「不存在」处理，不泄露「这个 id 存在但不归你」。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `message_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 全部标为已读

`POST /api/inbox/read-all`

**响应**

- `200` — 成功

### 删除全部已读消息

`DELETE /api/inbox/read`

只删自己、只删已读的；未读消息一条不动。重复调用返回 0，无副作用。

**响应**

- `200` — 成功

## 生日关怀

### 今日生日（首页条幅）

`GET /api/birthday/today`

首页条幅数据源 **匿名只给人数，姓名只给登录用户**。关键在返回体本身：匿名分支里 names 恒为 空数组 —— 不是「前端拿到再藏起来」，而是这个接口对未登录的人根本不吐姓名， 直接 curl 也拿不到。年龄也不在这里给（年龄只进功能 3 的通知正文）。 返回体形状恒定（四个字段永远都在），前端不用处理字段缺失。

**响应**

- `200` — 成功

### 读取生日关怀设置

`GET /api/admin/birthday/settings`

**响应**

- `200` — 成功

### 保存生日关怀设置

`PUT /api/admin/birthday/settings`

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `banner_enabled` | boolean | 是 |  |
| `banner_show_names` | boolean | 是 |  |
| `greet_enabled` | boolean | 是 |  |
| `greet_template` | string | 否 |  |
| `notify_enabled` | boolean | 是 |  |
| `notify_student_nos` | string[] | 否 |  |

**响应**

- `200` — 成功

### 给当前管理员自己发一条生日汇总测试消息

`POST /api/admin/birthday/test`

手动触发一次功能 3 的汇总通知 三个刻意的约束： 1. **只发给当前管理员自己**，绝不发给 notify_student_nos 里勾选的那些账号 —— 测试不该打扰别人。同 Bark / Webhook / 邮件测试端点「只发当前账号」的做法。 2. **不写 last_run_date**：否则管理员早上 7:59 手点一下，08:00 真该发的那一轮 就被幂等标记吃掉，而且不留任何痕迹。测试完全绕开标记，只调「组装 + 投递」。 3. 文案调用的是和每日任务**同一个** build_summary()，所以测的就是真发的那段。 数据用今天的真实寿星；今天没人过生日就用示例数据（否则一年 364 天没法验证格式）， 并在正文里标明是示例。

**响应**

- `200` — 成功

## 投票

### 投票列表

`GET /api/polls`

只列我该看得见的：管理员和发起人看全部，其他人在表决名单里才看得见 status 传了别的值就当没传（前端只会传这三个或空）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string，可空 | 按状态筛选：pending / open / closed |
| `keyword` | query | 否 | string，可空 | 按标题模糊搜索 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `PollListResponse` — 成功
  - 字段：`total`、`page`、`page_size`、`items`

### 发起投票（班委及以上）

`POST /api/polls`

出卷：题目、参与范围、起止时间、记名不记名，一次定完 发出去之后标题和描述随时能改（下面的 update_poll），**题目只有还没开始时能改** —— 作答存的是选项**下标**，已经开始之后再动题目会让历史作答整体错位。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 标题 |
| `description` | string | 否 | 描述 |
| `anonymous` | boolean | 否 | 不记名投票：接口层不再返回谁投了什么 |
| `start_at` | string（日期时间） | 是 | 开始时间 |
| `end_at` | string（日期时间） | 是 | 截止时间 |
| `targets` | string[] | 是 | 有权表决的学号（接口会核对是否真存在） |
| `questions` | PollQuestionIn[] | 是 | 一张卷子上的题 |

`questions` 的字段：

  - `title`：string（必填）
  - `multiple`：boolean
  - `max_choices`：integer（≥1，默认 1）
  - `options`：string[]（必填）

**响应**

- `200` `PollDetailResponse` — 成功
  - 字段：`id`、`title`、`description`、`anonymous`、`status`、`start_at`、`end_at`、`closed_at`、`creator_no`、`creator_name`、`created_at`、`question_count`、`target_count`、`voted_count`、`is_target`、`has_voted`、`results_visible`、`can_manage`、`can_vote`、`questions`

### 出卷可选的学生名单（班委及以上）

`GET /api/polls/roster`

出卷时勾人用：在校状态正常的学生，带「是不是班委」和「政治面貌」给快捷键 **「是不是班委」必须 join users.role，绝不能读 students.class_position** —— 那个字段学生自己在「我的信息 → 申请修改」里就能提交改，拿它当权限等于允许自我 提权（models/user.py 里 role 那一列写得很清楚）。这是最容易踩进去的一个坑。 政治面貌则是**学生档案里的普通字段**，读它没有问题 —— 「仅团员」筛的是身份、 不是权限。

**响应**

- `200` `PollRosterResponse` — 成功
  - 字段：`items`

### 投票详情

`GET /api/polls/{poll_id}`

题目 + 我的作答 + 结果（看不到结果时 tallies 是 None）+ can_vote 记名投票**不额外标注**，不记名才标出来（用户口径）：anonymous 字段就够了。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**响应**

- `200` `PollDetailResponse` — 成功
  - 字段：`id`、`title`、`description`、`anonymous`、`status`、`start_at`、`end_at`、`closed_at`、`creator_no`、`creator_name`、`created_at`、`question_count`、`target_count`、`voted_count`、`is_target`、`has_voted`、`results_visible`、`can_manage`、`can_vote`、`questions`

### 编辑投票（发起人/管理员）

`PATCH /api/polls/{poll_id}`

改标题、描述、时间和记名方式；还没开始的还能整卷换题目 **时间按状态分档**，不是「编辑时一概不能改」：还没开始的两个都能改（把开场时间 往后推 = 推迟开始，总比删了重发强）；**已经开始的只能改截止时间**（start_at 已经 过去了，改它没有任何意义，还会把「开始时锁题」那条规则的依据弄乱）；**已结束的 一个都不给改** —— closed_at 优先于时间判断，改了也不会生效，允许就是骗人。 **题目和记名与否都只在这张卷子还没开始时能改** —— 两样都会「换一张票」：题目换了 下标就错位（作答存的是选项**下标**，models/poll.py 的 PollQuestion 写着这件事）， 记名方式换了等于把已经投出去的票重新定义一遍（不记名的票突然有了主）。没开始时 库里不可能有这场投票的作答 —— can_vote 要求状态是 open，而 open 是按 start_at 现算的，没到点谁也提交不上来。所以那时把旧题删掉重建最省事：不用按题号去 diff （题干改了、选项多一个少一个都要小心对齐），也不会留下废题。 表决范围才是真的一个字都不能动 —— 见 schemas/poll.py 的 PollUpdate。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 标题 |
| `description` | string | 否 | 描述 |
| `start_at` | string（日期时间），可空 | 否 | 新的开始时间，不传=不改。只有还没开始的投票能改 |
| `end_at` | string（日期时间），可空 | 否 | 新的截止时间，不传=不改。已经开始的（含已暂停）也能调整 |
| `anonymous` | boolean，可空 | 否 | 记名还是匿名，不传=不改。只有还没开始的投票能改 |
| `questions` | PollQuestionIn[]，可空 | 否 | 传了就把题目整卷换掉，只对还没开始的投票有效 |

**响应**

- `200` `PollDetailResponse` — 成功
  - 字段：`id`、`title`、`description`、`anonymous`、`status`、`start_at`、`end_at`、`closed_at`、`creator_no`、`creator_name`、`created_at`、`question_count`、`target_count`、`voted_count`、`is_target`、`has_voted`、`results_visible`、`can_manage`、`can_vote`、`questions`

### 删除投票（发起人/管理员）

`DELETE /api/polls/{poll_id}`

删掉一场投票和它的全部痕迹 **允许删已经有人投过的**（前端确认框会写明「已有 N 人投票」）：不然一张发错的 卷子只要有人投过就永远纠正不了，只能一直挂在那里。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 投票（整卷一次提交）

`POST /api/polls/{poll_id}/vote`

一人一卷、整卷一次提交，**投过就不能再投**（不许改票） 下面三个判断合起来就是 poll_service.can_vote，拆开写只是为了让每种情况都回一句 说得清楚的话（can_vote 那边是个布尔，够 detail 用）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `answers` | PollAnswerIn[] | 是 |  |

`answers` 的字段：

  - `question_id`：integer（必填）
  - `choices`：integer[]（必填）

**响应**

- `200` `PollDetailResponse` — 成功
  - 字段：`id`、`title`、`description`、`anonymous`、`status`、`start_at`、`end_at`、`closed_at`、`creator_no`、`creator_name`、`created_at`、`question_count`、`target_count`、`voted_count`、`is_target`、`has_voted`、`results_visible`、`can_manage`、`can_vote`、`questions`

### 投票名单与记名明细（发起人/管理员）

`GET /api/polls/{poll_id}/ballots`

谁投了、谁没投（催票按它算未投人数）；记名投票再带上谁投了什么 **不记名投票一样给这份名单**，只是每行的 choices 恒为 None —— 「谁投了什么」在接口层就不返回（用户口径：不做数据库级不记名，接口级够了）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**响应**

- `200` `PollBallotsResponse` — 成功
  - 字段：`total`、`voted_count`、`rows`

### 催还没投的人（发起人/管理员）

`POST /api/polls/{poll_id}/remind`

给「还没投」的人各推一条提醒。四条口径： - 分母是**表决名单**（不是全班），只在名单里的人才有票可投 - **已投的跳过**：催了也没用，人家已经投了 - **冻结账号跳过**：投票接口会拒他们，推了也白推 - **操作人自己跳过**：他正对着页面点催票，再给自己推一条纯属噪音 前三条前端算按钮上的「未投 N 人」时要同样排除，否则按钮说 3 人、 提示说「已提醒 1 人」，发起人会以为漏推了（api/notices.py 专门写过这条教训）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**响应**

- `200` `PollRemindResponse` — 成功
  - 字段：`reminded`

### 立即结束（发起人/管理员）

`POST /api/polls/{poll_id}/close`

手动结束：把 closed_at 记成此刻。**重复调用幂等** 幂等不只是「不报错」：已经结束就不再改写 closed_at（否则「什么时候结束的」会 被每次点击往后推），也不再记日志（否则操作日志里会出现一串假记录）。 写 closed_at 而不是改 end_at —— 改了就再也看不出这场原本打算什么时候截止。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**响应**

- `200` `PollCloseResponse` — 成功
  - 字段：`status`、`voted_count`

### 暂停投票（发起人/管理员）

`POST /api/polls/{poll_id}/lock`

暂停收票。**暂停不是结束**：解锁后照样能投 到点还没解开就照常自动结束 —— 这条不用在这儿写任何代码，poll_service.poll_status 里判断截止时间那一条排在锁定之前，算出来的自然就是「已结束」（见那个函数的说明）。 只认「进行中」这一种状态：没开始的本来就没在收票，已结束的更谈不上暂停。 **重复调用幂等**（同 close_poll）：已经暂停就不再改写 locked_at、也不再记日志， 否则连点几次会把「什么时候暂停的」一直往后推。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**响应**

- `200` `PollDetailResponse` — 成功
  - 字段：`id`、`title`、`description`、`anonymous`、`status`、`start_at`、`end_at`、`closed_at`、`creator_no`、`creator_name`、`created_at`、`question_count`、`target_count`、`voted_count`、`is_target`、`has_voted`、`results_visible`、`can_manage`、`can_vote`、`questions`

### 恢复投票（发起人/管理员）

`POST /api/polls/{poll_id}/unlock`

恢复收票：把 locked_at 清回 NULL。**重复调用幂等** **不判当前状态、无条件清空**：暂停期间到了截止时间的那种，状态早就自己变成 已结束了，locked_at 却还挂在一条已结束的投票上。这时要是按状态判，会回一句 「只有已暂停的投票才能恢复」—— 用户看到的却只是「票结束了，暂停的标记还留着」。 清掉没有任何副作用：已结束的投票本来就不再收票。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `poll_id` | path | 是 | integer |  |

**响应**

- `200` `PollDetailResponse` — 成功
  - 字段：`id`、`title`、`description`、`anonymous`、`status`、`start_at`、`end_at`、`closed_at`、`creator_no`、`creator_name`、`created_at`、`question_count`、`target_count`、`voted_count`、`is_target`、`has_voted`、`results_visible`、`can_manage`、`can_vote`、`questions`

## 成绩

### 解析成绩 Excel 并预览（班委及以上，不写库）

`POST /api/grades/import/preview`

上传 Excel，返回识别结果与逐行结论（不写库，10 分钟内有效） 认不出的人、填错的格子都在返回里；确认入库时不再重新解析。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `sheet_name` | query | 否 | string，可空 | 工作表名，留空用第一张 |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 | Excel 文件 |

**响应**

- `200` `GradePreviewResponse` — 成功
  - 字段：`token`、`sheet_name`、`available_sheets`、`columns`、`sample_rows`、`student_count`、`matched_count`、`unmatched`、`name_mismatch`、`duplicates`、`problems`、`mark_values`、`warnings`

### 确认录入成绩（班委及以上）

`POST /api/grades/import`

按预览令牌把成绩写进库，然后给有成绩的学生发通知 subjects 是**保留**的科目名（勾掉的列连数据一起不要）：必须是预览里出现过的， 瞎传一个名字会让那一列静默变成 0 条成绩。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `token` | string | 是 | 预览令牌 |
| `name` | string | 是 | 测试名称 |
| `tested_at` | string | 是 | 测试日期（YYYY-MM-DD） |
| `remark` | string | 否 | 备注 |
| `subjects` | string[] | 是 | 要录入的科目名，顺序即列序 |
| `subject_modes` | object | 否 | 科目名 → score / pass_fail，没给的按计分 |
| `subject_full_scores` | object | 否 | 科目名 → 满分，没给的按 100（只对计分科目有意义） |
| `notify` | boolean | 否 | 录入后要不要给这些学生发通知 |

**响应**

- `200` `GradeImportResultResponse` — 成功
  - 字段：`test_id`、`name`、`subject_count`、`student_count`、`cell_count`、`skipped`、`message`、`warnings`

### 成绩列表（班委及以上）

`GET /api/grades`

列表只带两个聚合计数，不带明细（明细走 GET /{test_id}）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `keyword` | query | 否 | string，可空 | 按考试名称模糊搜索 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `GradeListResponse` — 成功
  - 字段：`total`、`page`、`page_size`、`items`

### 我的成绩（学生）

`GET /api/grades/mine`

只看自己的。**接口里没有任何能带别人学号的参数** —— 越权在形状上就不可能

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `keyword` | query | 否 | string | 按考试名称模糊搜索 |

**响应**

- `200` — 成功
  - 字段：MyGradeItem[]

### 成绩明细（班委及以上）

`GET /api/grades/{test_id}`

测试信息 + 科目列表 + 每个学生每格的成绩（每行每科都给键，空串 = 没录）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |

**响应**

- `200` `GradeDetailResponse` — 成功
  - 字段：`id`、`name`、`tested_at`、`remark`、`creator_no`、`creator_name`、`created_at`、`subjects`、`rows`、`mark_values`、`subject_count`、`student_count`

### 改测试信息（班委及以上）

`PATCH /api/grades/{test_id}`

名称 / 日期 / 备注，传了才改（明细页改完就地刷新，所以回整个明细）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string，可空 | 否 |  |
| `tested_at` | string，可空 | 否 |  |
| `remark` | string，可空 | 否 |  |

**响应**

- `200` `GradeDetailResponse` — 成功
  - 字段：`id`、`name`、`tested_at`、`remark`、`creator_no`、`creator_name`、`created_at`、`subjects`、`rows`、`mark_values`、`subject_count`、`student_count`

### 删除整次测试（班委及以上）

`DELETE /api/grades/{test_id}`

删整次测试：明细 → 科目 → 测试，一次提交 **顺序不能动**：SQLite 默认不开外键约束（database.py 没开 PRAGMA）， 先删父行的话子行就留在库里成了孤儿 —— 谁也删不掉、还占着「录入人数」的聚合。 同 api/polls.py 删投票的写法（那边也是逐表 delete 再删主表）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 单科统计（班委及以上）

`GET /api/grades/{test_id}/stats`

单科的平均分 / 最高 / 最低 / 及格率 / 分数段（通过制科目是「通过率」）。 **只有单科，没有总分、也没有跨科合计** —— 这个模块里不存在总分这个概念。 学生在「我的信息 → 我的成绩」里只看得到自己那一格的位次， 班级层面的这些数一律班委及以上（用户口径）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |

**响应**

- `200` `GradeStatsResponse` — 成功
  - 字段：`test_id`、`name`、`tested_at`、`subjects`、`roster_count`

### 加一科（班委及以上）

`POST /api/grades/{test_id}/subjects`

只建一行科目，格子按需补（新科目下所有人都还没成绩）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 科目名 |
| `mode` | string | 否 | score=计分 / pass_fail=通过制 |
| `full_score` | number（默认 100） | 否 | 满分（只对计分科目有意义） |

**响应**

- `200` `GradeSubjectResponse` — 成功
  - 字段：`id`、`name`、`sort`、`mode`、`full_score`

### 改一科的形态 / 满分（班委及以上）

`PATCH /api/grades/{test_id}/subjects/{subject_id}`

改某科记分数还是记通过 / 不通过，以及满分是多少（满分决定及格线与分数段）。 改形态前先看那一科**已有的数据跟不跟新形态对得上**：有分数却要改成通过制、 有「通过 / 不通过」却要改成计分，一律拒绝并说清是哪一科、有多少条。 **不做静默清空** —— 那是在替班委删数据：他点一下「改成通过制」不该弄丢一学期的分数。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |
| `subject_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `mode` | string，可空 | 否 | score=计分 / pass_fail=通过制 |
| `full_score` | number，可空 | 否 | 满分 |

**响应**

- `200` `GradeSubjectResponse` — 成功
  - 字段：`id`、`name`、`sort`、`mode`、`full_score`

### 删一科（班委及以上）

`DELETE /api/grades/{test_id}/subjects/{subject_id}`

删一科，连带它下面所有格子（先明细后科目，理由同删整次测试）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |
| `subject_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 写一个格子（班委及以上）

`PUT /api/grades/{test_id}/scores`

upsert 一个格子：没有记录就新建，清空（空串）就删除 按 (测试, 科目, 学号) 定位而不是按记录 id —— 这样「补录一个 Excel 里没有的学生」 才做得成（没有记录也有得写）。值不合法回 400 带一句具体的中文。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `test_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `student_no` | string | 是 | 学号 |
| `subject_id` | integer | 是 | 科目 ID |
| `value` | string | 否 | 空串 = 清空；分数；或标记词 |

**响应**

- `200` `GradeScoreResponse` — 成功
  - 字段：`student_no`、`subject_id`、`value`

## 日程

### List Schedules

`GET /api/schedules`

查询当前学生在指定日期范围内的日程（已展开重复日程）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `start_date` | query | 是 | string | 开始日期 |
| `end_date` | query | 是 | string | 结束日期 |

**响应**

- `200` — 成功
  - 字段：ScheduleResponse[]

### Create Schedule

`POST /api/schedules`

新建日程 普通学生：只能创建自己的日程（target_* 字段被忽略） 班委及以上：可通过 target_all / target_student_ids 批量创建

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 日程标题 |
| `event_type` | string | 否 | 事件类型，如 课程/体育/网络课 |
| `location` | string | 否 | 地点 |
| `description` | string | 否 | 备注 |
| `start_time` | string（日期时间） | 是 | 开始时间 |
| `end_time` | string（日期时间） | 是 | 结束时间 |
| `all_day` | boolean | 否 |  |
| `repeat_type` | string | 否 | 重复类型：none/weekly/monthly/odd_week/even_week |
| `repeat_end_date` | string，可空 | 否 | 重复结束日期（含） |
| `notify_enabled` | boolean | 否 | 是否开启通知（默认关闭） |
| `notify_minutes_before` | integer（≥1，≤1440，默认 10） | 否 | 提前多少分钟提醒 |
| `target_all` | boolean | 否 | 是否目标为全部学生（班委用） |
| `target_student_ids` | integer[] | 否 | 目标学生 ID 列表（班委用，target_all=false 时生效） |
| `share_from` | integer，可空 | 否 | 沿用这条日程当初的目标学生（班委用） |

**响应**

- `200` `ScheduleResponse` — 成功
  - 字段：`id`、`template_id`、`title`、`event_type`、`location`、`description`、`start_time`、`end_time`、`all_day`、`repeat_type`、`repeat_end_date`、`notify_enabled`、`notify_minutes_before`、`source_type`、`source_batch_id`、`share_count`、`instance_date`

### Search Schedules

`GET /api/schedules/search`

按名称搜自己的日程，每条日程只回一行（重复日程取离今天最近的一次） 页面上把它放在弹窗里：同名日程可能有很多条，得让用户按日期自己挑。 空关键词返回空列表，不整屏拉全班日程。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `keyword` | query | 否 | string | 日程名称关键词 |

**响应**

- `200` — 成功
  - 字段：ScheduleResponse[]

### Get Semester Info

`GET /api/schedules/semester`

各学期的周次范围 —— 页面上的「第几周」只在范围内编号 课表导入时在每条日程上写下 week_start（第 1 周的周一，由导入时确认的周次锚点 推算），同一份课表的所有日程共用它；而这份课表**实际覆盖到**的第一天和最后一天 就圈出了区间。所以按 week_start 分组、取每组覆盖范围的上下界，就得到一个个区间。 **基准和覆盖范围是两回事**：导入一份只含「第 8–10 周」的补课表时，锚点推出的 第 1 周在 7 周之前，但这份表只管第 8–10 周 —— 区间收在覆盖范围内，别把没覆盖到 的周算成自己的周次，不然会和别的导入批次的编号打架。 **为什么要带上界**：以前只给一个基准不给范围，页面按「距基准几周」一直往下算， 课表只有 16 周，翻到次年 5 月却显示「第 35 周」。区间外现在一律不编号。 **为什么是列表**：下学期再导入一份新课表，表名又从「第1周」开始 —— 那本就是 另一个区间、另一个「第 1 周」。多个第一周是对的。 区间在老数据上按现有日程的跨度兜一个，一条日程都没有时为空列表（前端就不显示 周次）。这套口径日程展开那边（单双周判断）也在用，见 schedule_service.list_semester_periods。

**响应**

- `200` `SemesterInfoResponse` — 成功
  - 字段：`periods`

### Get Schedule

`GET /api/schedules/item/{schedule_id}`

获取单条日程详情

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `schedule_id` | path | 是 | integer |  |
| `instance_date` | query | 是 | string | 实例日期（重复日程用） |

**响应**

- `200` `ScheduleResponse` — 成功
  - 字段：`id`、`template_id`、`title`、`event_type`、`location`、`description`、`start_time`、`end_time`、`all_day`、`repeat_type`、`repeat_end_date`、`notify_enabled`、`notify_minutes_before`、`source_type`、`source_batch_id`、`share_count`、`instance_date`

### Update Schedule

`PUT /api/schedules/item/{schedule_id}`

编辑日程 scope 参数控制编辑范围： - single：仅本次 - forward：本次及以后 - all：全部（默认） share 为真时，同一条原始日程在其他学生表里的副本一起改（见 schedule_service）。 放 query 而不是 body：下面 update_data 会把 body 里所有非 scope 字段当业务 字段写进模型，混一个控制参数进去早晚要出事。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `schedule_id` | path | 是 | integer |  |
| `instance_date` | query | 是 | string | 要编辑的实例日期 |
| `share` | query | 否 | boolean | 是否一并改掉其他学生的表（仅限分配者） 默认 `False` |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string，可空 | 否 |  |
| `event_type` | string，可空 | 否 |  |
| `location` | string，可空 | 否 |  |
| `description` | string，可空 | 否 |  |
| `start_time` | string（日期时间），可空 | 否 |  |
| `end_time` | string（日期时间），可空 | 否 |  |
| `all_day` | boolean，可空 | 否 |  |
| `repeat_type` | string，可空 | 否 |  |
| `repeat_end_date` | string，可空 | 否 |  |
| `notify_enabled` | boolean，可空 | 否 |  |
| `notify_minutes_before` | integer（≥1，≤1440），可空 | 否 |  |
| `scope` | string | 否 | 编辑范围：single/forward/all |

**响应**

- `200` `ScheduleResponse` — 成功
  - 字段：`id`、`template_id`、`title`、`event_type`、`location`、`description`、`start_time`、`end_time`、`all_day`、`repeat_type`、`repeat_end_date`、`notify_enabled`、`notify_minutes_before`、`source_type`、`source_batch_id`、`share_count`、`instance_date`

### Delete Schedule

`DELETE /api/schedules/item/{schedule_id}`

删除日程 share 为真时，同一条原始日程在其他学生表里的副本一起删。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `schedule_id` | path | 是 | integer |  |
| `scope` | query | 否 | string | 删除范围：single/forward/all 默认 `all` |
| `instance_date` | query | 是 | string | 实例日期 |
| `share` | query | 否 | boolean | 是否一并从其他学生的表里删掉（仅限分配者） 默认 `False` |

**响应**

- `200` — 成功

### Import Preview

`POST /api/schedules/import/preview`

上传日程 Excel 并预览解析结果（班委及以上） anchor_monday 不给就先按表头日期猜一个建议值返回（响应里带回来）；页面让用户 确认或改过之后，带上来再解析一次，所有日期都以它为准。

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 |  |
| `anchor_monday` | string，可空 | 否 | 周次锚点：文件里最小周次那一周的周一 |

**响应**

- `200` `ScheduleImportPreviewResponse` — 成功
  - 字段：`token`、`week_count`、`week_first`、`week_last`、`anchor_monday`、`schedule_count`、`all_day_count`、`items`、`warnings`

### Import Confirm

`POST /api/schedules/import`

确认导入日程（班委及以上）

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `token` | string | 是 | 预览令牌 |
| `batch_name` | string | 否 | 批次名称 |
| `target_all` | boolean | 否 | 是否导入给全部学生 |
| `target_student_ids` | integer[] | 否 | 目标学生 ID 列表（target_all=false 时生效） |
| `selected_indices` | integer[] | 否 |  |

**响应**

- `200` `ScheduleImportResultResponse` — 成功
  - 字段：`batch_id`、`batch_name`、`target_count`、`schedule_per_student`、`total_created`、`warnings`

### List Batches

`GET /api/schedules/batches`

查看自己创建的导入批次

**响应**

- `200` — 成功
  - 字段：ScheduleBatchResponse[]

### Delete Batch

`DELETE /api/schedules/batches/{batch_id}`

撤销整个导入批次（删除该批次下所有日程）

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `batch_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### Get Ical Token

`GET /api/schedules/ical/token`

获取当前学生的 iCal 订阅链接

**响应**

- `200` `ICalTokenResponse` — 成功
  - 字段：`token`、`url`、`last_accessed_at`

### Reset Ical Token

`POST /api/schedules/ical/token/reset`

重置 iCal 订阅令牌（旧链接立即失效）

**响应**

- `200` `ICalTokenResponse` — 成功
  - 字段：`token`、`url`、`last_accessed_at`

### Ical Feed

`GET /api/schedules/ical/{token}.ics`

iCal 订阅端点（公开接口，通过 URL 中的 token 鉴权） 返回标准 .ics 文件内容。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `token` | path | 是 | string |  |

**响应**

- `200` — 成功

## 签字

### 签字查看申请列表（仅管理员）

`GET /api/sign-photos/requests`

审批用的列表。待审的排前面，其余按时间倒序

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | query | 否 | string，可空 | 按状态筛选：pending / approved / rejected |
| `keyword` | query | 否 | string，可空 | 按提交人姓名或学号模糊搜索 |
| `start` | query | 否 | string，可空 | 提交日期起始，含当天 |
| `end` | query | 否 | string，可空 | 提交日期结束，含当天 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤100，默认 20） | 默认 `20` |

**响应**

- `200` `SignPhotoRequestListResponse` — 成功
  - 字段：`total`、`items`

### 申请查看签字（班委及以上）

`POST /api/sign-photos/requests`

班委申请看某个学生的签字图，等管理员批 同一个学生对同一个申请人只留一条有效的：待审的不许重复提交，批下来还没过期的 也不必再申请（否则自己反复申请就能把有效期无限往后滚）。过期或已被驳回的可以重来。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `student_id` | integer | 是 | 被查看签字的学生 ID |

**响应**

- `200` `SignPhotoRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`applicant_no`、`applicant_name`、`status`、`reason`、`created_at`、`reviewed_at`、`reviewer_name`

### 我自己的签字图状态（学生本人）

`GET /api/sign-photos/my-status`

只回答「传没传」，**连文件名都不给** 学生可以上传自己的签字图，但不能查看、下载或删除，所以这里不能复用 /status/{student_id}（那条要班委且会返回 download_name）。页面只靠这个 布尔值决定按钮写「上传签字图」还是「重新上传」。

**响应**

- `200` — 成功

### 我对某学生签字的状态（班委及以上）

`GET /api/sign-photos/status/{student_id}`

详情页那个按钮的状态，顺带给出预览要用的下载名 管理员不用申请：有图就是能看，状态直接是 approved。 **有图就一定有 download_name**，哪怕当前状态是「没申请过」—— 前端靠它区分 「这学生根本没有签字图」（不渲染按钮）和「有图但我还没申请」（渲染「申请签署」）。 只有 download_name 一个信号，状态字符串不够用。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |

**响应**

- `200` `SignPhotoStatusResponse` — 成功
  - 字段：`status`、`expires_at`、`download_name`

### 通过签字查看申请（仅管理员）

`POST /api/sign-photos/requests/{request_id}/approve`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `request_id` | path | 是 | integer |  |

**响应**

- `200` `SignPhotoRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`applicant_no`、`applicant_name`、`status`、`reason`、`created_at`、`reviewed_at`、`reviewer_name`

### 驳回签字查看申请（仅管理员）

`POST /api/sign-photos/requests/{request_id}/reject`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `request_id` | path | 是 | integer |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `reason` | string | 是 | 驳回理由 |

**响应**

- `200` `SignPhotoRequestResponse` — 成功
  - 字段：`id`、`student_id`、`student_no`、`student_name`、`applicant_no`、`applicant_name`、`status`、`reason`、`created_at`、`reviewed_at`、`reviewer_name`

### 取签字图（管理员，或获批的那个班委）

`GET /api/sign-photos/image/{student_id}`

签字图的唯一出口 判定顺序是有意排的：先看「你是谁」（学生和外部用户直接 403，不让他们知道 有这么个东西），再看「你有没有权限」，最后才碰文件。管理员短路放行，不需要申请。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 上传/替换签字图（管理员，或学生本人）

`POST /api/sign-photos/image/{student_id}`

管理员可以给任何学生传，学生只能传自己的。页面里都不显示这张图 权限判定只有两种放行情形：管理员；或当前账号就是这个学生本人。班委传别人的 一律 403 —— 「能看名单」不等于「能替人签字」。 落盘顺序照项目既有约定：新文件先写盘 → 写库 → 提交成功后才删旧文件。任何一步 失败，库里那行指向的文件都还在（宁可留一个没人引用的孤儿文件，也不能让档案 指向一张不存在的图）。 换图之后**已批准的班委自动看到新图**，旧的有效期不作废 —— 权限是「看这个学生的 签字」，不是「看这一版签字」。要作废得另说。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 | 签字图片 |

**响应**

- `200` — 成功

### 删除签字图（仅管理员）

`DELETE /api/sign-photos/image/{student_id}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

## 通行密钥

### 列出我的通行密钥

`GET /api/auth/passkeys`

**响应**

- `200` `PasskeyListResponse` — 成功
  - 字段：`items`、`max_count`

### 登记通行密钥：第一步，取选项

`POST /api/auth/passkeys/register/options`

要再输一次密码才给选项：登录态可能是别人借你电脑留下的，不能因此就让他 给自己塞一把长期钥匙

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `password` | string | 是 |  |
| `label` | string | 否 | 备注名，例如「我的 iPhone」 |

**响应**

- `200` — 成功

### 登记通行密钥：第二步，验证并保存

`POST /api/auth/passkeys/register/verify`

**不校验 credential_id 是否重复后再覆盖**：重复登记一律拒绝。 浏览器按 excludeCredentials 本来就会拦，真走到这里说明有问题， 悄悄换成另一把等于把「谁占了这个位置」搞乱。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `password` | string | 是 |  |
| `label` | string | 否 | 备注名，例如「我的 iPhone」 |
| `credential` | object | 是 |  |

**响应**

- `200` — 成功

### 删除我的一把通行密钥

`DELETE /api/auth/passkeys/{passkey_id}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `passkey_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 通行密钥登录：第一步，取选项

`POST /api/auth/passkeys/login/options`

不点名任何账号：allowCredentials 留空，由浏览器列出本机上属于本站的钥匙， 用户挑一把、过指纹 / 面容 / PIN 即可。谁登录留到第二步按凭据反查。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remember` | boolean | 否 | 是否保持登录 7 天 |

**响应**

- `200` — 成功

### 通行密钥登录：第二步，验证并登录

`POST /api/auth/passkeys/login/verify`

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `remember` | boolean | 否 | 是否保持登录 7 天 |
| `credential` | object | 是 |  |

**响应**

- `200` — 成功

## 二次验证

### 校验登录二次验证码

`POST /api/auth/2fa/verify`

第二因素通过后才真正写登录会话 通行密钥登录不会走到这里（见 api/passkeys.py）：钥匙本身已经是第二因素。 邮件验证码、TOTP 验证码、一次性恢复码都填在同一个框里提交，后端先试 当前方式，不中再试恢复码；恢复码命中即作废，并在响应里告诉还剩几个。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | string | 是 | 验证码或一次性恢复码 |

**响应**

- `200` — 成功

### 重新发送登录验证码

`POST /api/auth/2fa/resend`

只对邮箱方式有效；60 秒冷却 重发换一个新码，旧码立即失效。**尝试次数不清零** —— 否则拿到密码的人 可以每 60 秒重发一次，把 5 次机会滚成无限次。

**响应**

- `200` — 成功

### 我的二次验证设置

`GET /api/auth/2fa/status`

页面靠它决定显示「已开启」还是开启入口 email 是实际会收验证码的地址（覆盖值优先，其次档案邮箱）；没有可用地址时 是空串，前端要把「电子邮件验证码」那一块置灰并说明原因。

**响应**

- `200` — 成功

### 发送开启邮箱二次验证的验证码

`POST /api/auth/2fa/email/send`

先发一封测试码，确认这个邮箱真能收到，再允许开启 复用消息通知的 SMTP 与地址口径，但**不看 notify_email_enabled**： 二次验证是登录的一部分，不是「订阅通知」。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `password` | string | 是 | 登录密码 |

**响应**

- `200` — 成功

### 确认邮箱验证码并开启

`POST /api/auth/2fa/email/confirm`

输对验证码才真正把 method 改成 email，并生成恢复码 恢复码明文只出现在这一次响应里；后端只留哈希。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | string | 是 |  |

**响应**

- `200` — 成功

### 生成一个待确认的 TOTP 密钥

`POST /api/auth/2fa/totp/begin`

只生成密钥，**先不写进账号**：等用户输对一次 App 里的码再确认 密钥放在挑战表里，10 分钟没确认就作废。重复点「开始设置」以最后一次为准。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `password` | string | 是 | 登录密码 |

**响应**

- `200` — 成功

### 确认 TOTP 验证码并开启

`POST /api/auth/2fa/totp/confirm`

App 里显示的 6 位码对得上，才把密钥搬到账号上并生成恢复码

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | string | 是 |  |

**响应**

- `200` — 成功

### 关闭二次验证

`POST /api/auth/2fa/disable`

关闭后回到「只要密码」的登录方式，恢复码和待确认的挑战一并清掉

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `password` | string | 是 | 登录密码 |

**响应**

- `200` — 成功

### 重新生成 10 个一次性恢复码

`POST /api/auth/2fa/recovery/regenerate`

旧码整批作废；新码只在这条响应里出现一次

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `password` | string | 是 | 登录密码 |

**响应**

- `200` — 成功

## 系统管理

### 账号列表

`GET /api/admin/users`

**响应**

- `200` — 成功
  - 字段：AdminUserResponse[]

### 设置角色

`PUT /api/admin/users/{student_no}/role`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `role` | string | 是 |  |

**响应**

- `200` — 成功

### 重置密码

`POST /api/admin/users/{student_no}/reset-password`

两种账号，两种重置方式： - 学生账号：重置成「身份证号后 6 位」并重新要求首次登录改密。 没有身份证号的退回学号后 6 位，那种情况下接口会把密码回带给管理员， 好让管理员转告学生（学号后 6 位本来就不是秘密）。 这里会忽略请求体里的密码 —— 学生账号不允许管理员指定密码。 - 域外账号：没有身份证号可依据，由管理员在请求体里直接指定新密码， 设完即可用、不再要求首次登录改密。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |

**请求体**（`application/json`，JSON）

类型：ResetPasswordRequest，可空

**响应**

- `200` `ResetPasswordResponse` — 成功
  - 字段：`message`、`password`、`fallback`

### 冻结账号

`POST /api/admin/users/{student_no}/freeze`

冻结学生账号和域外账号都行（_get_user 不区分类别） 不需要额外判断「是不是最后一个未冻结的管理员」——下面那道「不能冻自己」 已经把它盖住了，理由是： 调用者此刻**必定是未冻结的管理员**（admin_required 查的是库里的实时角色， 冻结的账号在 get_current_user 里就被 401 挡掉，根本进不到这个函数）， 而它冻不了自己，所以冻完任何一个目标之后，系统里至少还剩它这一个 未冻结管理员。目标不是自己、又是个管理员时，未冻结管理员必然 ≥ 2 个， 「冻完就没管理员了」这种情况不可能出现。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |

**响应**

- `200` — 成功

### 解冻账号

`POST /api/admin/users/{student_no}/unfreeze`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |

**响应**

- `200` — 成功

### 清除该账号的全部通行密钥

`DELETE /api/admin/users/{student_no}/passkeys`

换手机、丢了手机又没开云同步时的退路：清掉之后用密码登录即可 只删通行密钥，不动密码、不踢会话 —— 通行密钥是「多一种进门方式」， 清掉它不会让正在用的人掉线，也不会让账号失去密码登录能力。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |

**响应**

- `200` — 成功

### 清除该账号的二次验证

`DELETE /api/admin/users/{student_no}/2fa`

手机丢了、验证器又没备份恢复码时的退路：关掉之后用密码登录即可 只清二次验证相关的数据，不动密码、不踢会话 —— 和清除通行密钥同理， 这是「少一道门槛」，不是「让账号下线」。 待确认的开启挑战和正在等待校验的登录挑战一并删掉：留着的话， 用户下一次输入的码会因为「设置已变化」被拒，反而更困惑。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |

**响应**

- `200` — 成功

### 吊销该账号的所有会话

`POST /api/admin/users/{student_no}/revoke-sessions`

把这个账号在所有设备上的登录一次性踢掉，但**不禁止它重新登录** 用途是「密码可能泄露了，先把所有设备登出」这类不想停用账号的场合。 和冻结的区别：冻结是禁止登录（is_frozen），这个是允许登录、只让已签发的 cookie 作废。 会话是签名 Cookie、服务端没有会话表，所以这里不是去删什么记录，而是把 session_epoch +1；deps.get_current_user 每次请求拿 cookie 里的代次和这一列比对， 对不上的下一个请求就 401。全部设备一起生效，不用挨个通知。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |

**响应**

- `200` — 成功

### 某个账号的日志

`GET /api/admin/users/{student_no}/logs`

三块内容： - 操作日志：这个账号**作为操作人**留下的全部记录，分页 - 被操作记录：这个账号**作为操作对象**的记录（别人重置他的密码、改他的 角色、改他的学生信息、审批他的申请……），分页 - 账号事件：这个账号最近 7 天的登录 / 自行改密 事件那块只能查到本功能上线之后 —— 之前这两种行为压根没入库， 不存在的历史补不回来（不是漏查，是从来没有）。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `student_no` | path | 是 | string |  |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤200，默认 20） | 默认 `20` |
| `target_page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `target_page_size` | query | 否 | integer（≥1，≤200，默认 20） | 默认 `20` |

**响应**

- `200` `AdminUserLogsResponse` — 成功
  - 字段：`student_no`、`name`、`operations`、`targeted`、`events`、`events_total`、`events_since`

### 新建域外账号

`POST /api/admin/external-users`

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `login_name` | string | 是 | 登录名（就是登录时填在学号那一栏的东西） |
| `display_name` | string | 是 | 展示用户名（姓名、水印都用它） |
| `password` | string | 是 | 初始密码 |
| `role` | string | 否 | 等效权限 |
| `avatar` | string，可空 | 否 | 头像，可选 |
| `sign_photo` | string，可空 | 否 | 签字图，可选 |

**响应**

- `200` — 成功

### 修改域外账号

`PUT /api/admin/external-users/{login_name}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `login_name` | path | 是 | string |  |

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `display_name` | string | 是 |  |
| `role` | string | 是 |  |
| `remove_avatar` | boolean | 否 | 是否删掉现有头像 |
| `avatar` | string，可空 | 否 | 新头像，可选；传了就换掉旧的 |
| `remove_sign_photo` | boolean | 否 | 是否删掉现有签字图 |
| `sign_photo` | string，可空 | 否 | 新签字图，可选；传了就换掉旧的 |

**响应**

- `200` — 成功

### 删除域外账号

`DELETE /api/admin/external-users/{login_name}`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `login_name` | path | 是 | string |  |

**响应**

- `200` — 成功

### 取域外账号的签字图（仅管理员）

`GET /api/admin/external-users/{login_name}/sign-photo`

域外账号的签字图**只有管理员能取** 域外账号本人、学生、班委一律 403（admin_required 就挡住了）—— 签字是审批落款 用的，不拿去给谁看。地址固定而图会随替换改变，所以 no-store，绝不能缓存。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `login_name` | path | 是 | string |  |

**响应**

- `200` — 成功

### 操作日志

`GET /api/admin/logs`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `operator` | query | 否 | string，可空 | 按操作人姓名或学号模糊搜索 |
| `action` | query | 否 | string，可空 | 按动作模糊搜索 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤200，默认 50） | 默认 `50` |

**响应**

- `200` `OperationLogListResponse` — 成功
  - 字段：`total`、`items`

### 清空操作日志

`DELETE /api/admin/logs`

删除全部操作日志，**然后补一条「清空了日志」** 清空本身也是要留痕的动作 —— 否则日志突然变空之后谁也说不清是清过、 还是库出问题了。清掉了多少条写进 detail，两次清空之间对得上账。 顺序是先删后写，`query.delete()` 是立即执行的批量删除（不是挂到 flush 上）， 所以补的那条不会被自己删掉。

**响应**

- `200` — 成功

### 封禁中的 IP 列表

`GET /api/admin/ip-bans`

只列**生效中**的封禁（过期行在 SQL 里过滤掉）。 过期行留在表里不清：清的理由只有「列表好看」， 而清的动作要么放在 GET 里（写库还忘了 commit 就静默无效，没人会注意）， 要么加一堆定时任务。启动时 purge 一次已经够，平时让它们躺着不影响任何判定。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `target` | query | 否 | string，可空 | 按 IP 或网段模糊搜索 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤200，默认 50） | 默认 `50` |

**响应**

- `200` `IpBanListResponse` — 成功
  - 字段：`total`、`items`、`self_ip`

### 手动封禁 IP 或网段

`POST /api/admin/ip-bans`

手动封禁。三步校验的顺序是有讲究的，别调换（见下面每条的理由）。

**请求体**（`application/json`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `target` | string | 是 | IP 或 CIDR 网段，如 203.0.113.9 或 203.0.113.0/24 |
| `minutes` | integer（≥1，≤5256000），可空 | 否 | 封禁分钟数，留空表示永久（上限 10 年） |
| `reason` | string | 否 | 封禁原因 |

**响应**

- `200` — 成功

### 解除 IP 封禁

`DELETE /api/admin/ip-bans/{ban_id}`

按主键解封。 接口参数用自增 id 而不是 target：IPv6 和网段里的 / : % 在 URL 路径里 都要转义，转完还可能被中间层还原错，踩一次很难查。前端列表里本来就有 id。 解封后必须清掉内存里的失败计数，否则该 IP 下次输错一次立刻又被自动封， 管理员会以为「解封没生效」。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `ban_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 资料列表（管理员用）

`GET /api/admin/resources`

返回所有资料条目，不分组，按分类+排序。 管理界面用，方便做拖拽排序和增删改。

**响应**

- `200` — 成功

### 上传新资料

`POST /api/admin/resources`

上传一个新资料到指定分类 文件存到 data/downloads/，文件名用 UUID 前缀（防路径穿越和重名覆盖）。

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 显示名称 |
| `category` | string | 是 | 分类名称 |
| `file` | string | 是 | 资料文件 |

**响应**

- `200` — 成功

### 修改资料信息

`PUT /api/admin/resources/{resource_id}`

只改名称和/或分类，不改文件本身

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `resource_id` | path | 是 | integer |  |

**请求体**（`application/x-www-form-urlencoded`，JSON）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 否 | 新的显示名称 |
| `category` | string | 否 | 新的分类 |

**响应**

- `200` — 成功

### 删除资料

`DELETE /api/admin/resources/{resource_id}`

同时删除数据库记录和磁盘文件。不可恢复。

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `resource_id` | path | 是 | integer |  |

**响应**

- `200` — 成功

### 调整资料分类的展示顺序

`PUT /api/admin/resources/categories/order`

按给定顺序显示分类（数组顺序即页面顺序） 只影响「分类之间」的先后；分类里的资料顺序仍由 /resources/reorder/{category} 管。

**请求体**（`application/json`，JSON）

类型：string[]

**响应**

- `200` — 成功

### 重排某分类下的资料顺序

`PUT /api/admin/resources/reorder/{category}`

按给定的 ID 列表重排某个分类内的资料顺序

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `category` | path | 是 | string |  |

**请求体**（`application/json`，JSON）

类型：integer[]

**响应**

- `200` — 成功

### 文件访问日志（查看/下载）

`GET /api/admin/file-access-logs`

**参数**

| 名称 | 位置 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| `user` | query | 否 | string，可空 | 按访问人姓名或学号模糊搜索 |
| `file` | query | 否 | string，可空 | 按文件标题模糊搜索 |
| `action` | query | 否 | string，可空 | 按动作筛选：view / download，留空=全部 |
| `page` | query | 否 | integer（≥1，默认 1） | 默认 `1` |
| `page_size` | query | 否 | integer（≥1，≤200，默认 50） | 默认 `50` |

**响应**

- `200` `FileAccessLogListResponse` — 成功
  - 字段：`total`、`items`

### 从 PDF 中提取不可见水印（溯源）

`POST /api/admin/file-access-logs/extract`

上传一份 PDF，提取里面的不可见水印令牌，解析出下载人、时间、文件信息

**请求体**（`multipart/form-data`，文件上传）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 是 | 待提取水印的 PDF 文件 |

**响应**

- `200` `WatermarkExtractResponse` — 成功
  - 字段：`found`、`token`、`file_id`、`user_no`、`user_name`、`file_title`、`accessed_at`、`source_type`、`export_type`、`export_scope`、`export_status`、`export_reviewer`、`action`、`ip`、`log_matched`、`file_deleted`、`message`

### 学生数据体检（仅管理员）

`GET /api/admin/data-health`

把学生表里的脏数据逐项查出来（只报告，不改数据） 每次都全表扫一遍，不缓存也不落库：一个班几十人，查询本身就是毫秒级， 而「上次体检是什么时候」这种状态一旦存下来就得考虑失效。

**响应**

- `200` `DataHealthResponse` — 成功
  - 字段：`checked_at`、`total_students`、`groups`

## 健康检查

### 健康检查

`GET /api/health`

不需要登录。部署脚本与容器健康检查用它确认后端活着，同时取出当前版本号。

**响应**

```json
{"status": "ok", "app": "班级信息管理系统", "version": "1.17.13"}
```
