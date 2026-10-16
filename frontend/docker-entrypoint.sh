#!/bin/sh
set -e

# 默认值
export NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"
export NGINX_TRUST_PROXY="${NGINX_TRUST_PROXY:-on}"
export NGINX_TRUSTED_PROXIES="${NGINX_TRUSTED_PROXIES:-172.16.0.0/12}"
# 70M：意见反馈最多 3 个附件、单个上限 20MB，3×20=60MB 再加上表单正文，
# 低于这个值会在 FastAPI 之前就被 nginx 用 413 挡掉（返回 HTML 错误页，
# 前端只能弹一句「提交失败」，极难排查）
export NGINX_CLIENT_MAX_BODY_SIZE="${NGINX_CLIENT_MAX_BODY_SIZE:-70M}"

# 组装信任代理的配置块
if [ "$NGINX_TRUST_PROXY" = "on" ]; then
    # real_ip_header：从哪个头里取真实 IP
    # set_real_ip_from：哪些 IP 发来的头可以信任
    # real_ip_recursive：多层代理时递归取最后一个不可信的
    TRUST_PROXY_BLOCK="real_ip_header X-Forwarded-For;
    real_ip_recursive on;"
    # 把 NGINX_TRUSTED_PROXIES 里用空格分隔的每个 IP 都加一行 set_real_ip_from
    for proxy_ip in $NGINX_TRUSTED_PROXIES; do
        TRUST_PROXY_BLOCK="$TRUST_PROXY_BLOCK
    set_real_ip_from $proxy_ip;"
    done
else
    TRUST_PROXY_BLOCK=""
fi
export TRUST_PROXY_BLOCK

# 组装 HTTPS server block（证书和私钥都配置了才开启）
SSL_SERVER_BLOCK=""
if [ -n "$NGINX_SSL_CERT" ] && [ -n "$NGINX_SSL_KEY" ]; then
    SSL_SERVER_BLOCK="server {
    listen 443 ssl http2;
    server_name ${NGINX_SERVER_NAME};

    client_max_body_size ${NGINX_CLIENT_MAX_BODY_SIZE};

    ssl_certificate $NGINX_SSL_CERT;
    ssl_certificate_key $NGINX_SSL_KEY;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    $TRUST_PROXY_BLOCK

    root /usr/share/nginx/html;
    index index.html;

    location ^~ /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \"upgrade\";

        # 超时设置。这几个 nginx 自己的超时都是「两次相邻读写之间」的间隔，
        # 不是整个请求的总时长 —— 稳步上传的慢网络不会触发，但手机信号断一下
        # 超过 60 秒就断了。放宽到 5 分钟，和前端给文件传输的超时对齐。
        proxy_connect_timeout 60s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_body_timeout 300s;
        send_timeout 300s;

        # 这里原来有一句 add_header Cache-Control \"no-store\"。**不要加回来**：
        # add_header 是追加不是覆盖，会把后端特意设的照片缓存顶成两个头、
        # no-store 生效。完整理由见 nginx.conf.template 里的同名注释。
        # 那句已经搬进后端 middleware.DefaultCacheControlMiddleware。
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Service Worker 和首页绝不能缓存（理由见 nginx.conf.template，写得更详细）。
    # 这两条 location 里没有任何 NGINX 变量，envsubst 不会动它们
    location = /sw.js {
        add_header Cache-Control \"no-cache, no-store, must-revalidate\";
    }

    location = /index.html {
        add_header Cache-Control \"no-cache\";
    }

    # 运行时注入的品牌文件与可替换的品牌图片，绝不能落进下面那条按扩展名的
    # 1 年 immutable 规则，否则改了 .env 里的班级名或换了校徽，老访客一年都看不到。
    # 精确匹配（=）和 ^~ 前缀的优先级都高于正则，写在哪一行都生效。
    location = /site-config.js {
        add_header Cache-Control \"no-cache\";
    }

    location = /manifest.webmanifest {
        # 类型：nginx 自带的 mime.types 里没有 webmanifest，会落到 application/octet-stream，
        # 标准类型是 application/manifest+json（完整说明见 nginx.conf.template）
        types {
            application/manifest+json webmanifest;
        }
        add_header Cache-Control \"no-cache\";
    }

    location = /logo.png {
        add_header Cache-Control \"no-cache\";
    }

    location = /favicon.png {
        add_header Cache-Control \"no-cache\";
    }

    location ^~ /icons/ {
        add_header Cache-Control \"no-cache\";
    }

    # ES Module 的 .mjs：nginx 自带 mime.types 里没有这条，会落到 application/octet-stream，
    # 而浏览器对 module worker 强制校验 MIME，pdf.js 的 worker 就加载不了、只能退回主线程。
    # 类型只能在 types 块里补，types 块又会整份替换掉继承来的 mime.types，
    # 所以单开一个只匹配 .mjs 的 location（完整说明见 nginx.conf.template）
    location ~* \.mjs$ {
        types {
            application/javascript mjs;
        }
        expires 1y;
        add_header Cache-Control \"public, immutable\";
    }

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control \"public, immutable\";
    }

    gzip on;
    gzip_min_length 1k;
    gzip_comp_level 6;
    # Vary: Accept-Encoding，理由见 nginx.conf.template 里同名那一句
    gzip_vary on;
    # application/rss+xml 得单独列，只写 application/xml 匹配不上它
    gzip_types text/plain text/css text/javascript application/json application/javascript application/xml application/rss+xml;
}"
fi
export SSL_SERVER_BLOCK

# 如果宿主机在 data/frontend/ 下提供了自定义配置，用它替换默认模板。
# 两个文件名都认（nginx.conf 优先，其次 nginx.conf.template），内容都是模板：
# 下面的 envsubst 带了白名单，只会替换 ${NGINX_SERVER_NAME} 等 4 个变量，
# nginx 自己的 $uri / $host 一律原样保留，所以直接写普通 nginx.conf 也不会被改坏。
TEMPLATE_FILE=/etc/nginx/templates/default.conf.template
DEFAULT_TEMPLATE=/etc/nginx/templates/default.conf.template.orig

# 先把模板还原成镜像里的原始版本。
# 为什么必须还原：docker compose restart 不重建文件系统，上一次 cp 进来的
# 自定义模板会留在原地，于是「删掉自定义配置再重启」会继续沿用旧的自定义配置。
if [ -f "$DEFAULT_TEMPLATE" ]; then
    cp "$DEFAULT_TEMPLATE" "$TEMPLATE_FILE"
else
    cp "$TEMPLATE_FILE" "$DEFAULT_TEMPLATE"
fi

for CUSTOM_CONF in /app/custom/nginx.conf /app/custom/nginx.conf.template; do
    if [ -f "$CUSTOM_CONF" ]; then
        cp "$CUSTOM_CONF" "$TEMPLATE_FILE"
        echo "[nginx] 已使用 $CUSTOM_CONF 作为自定义配置模板"
        break
    fi
done

# 用 envsubst 生成最终配置。
# 注意：只替换我们定义过的变量，否则 nginx 配置里的 $host / $uri 之类的 nginx 变量也会被替换掉！
envsubst '${NGINX_SERVER_NAME} ${NGINX_CLIENT_MAX_BODY_SIZE} ${TRUST_PROXY_BLOCK} ${SSL_SERVER_BLOCK}' \
    < "$TEMPLATE_FILE" \
    > /etc/nginx/conf.d/default.conf

# 去掉模板文件，避免混淆
rm -f /etc/nginx/conf.d/default.conf.template

# ==================== 品牌信息注入 ====================
# 前端镜像是 CI 预构建的，Vite 的构建期变量在部署侧不存在 —— 品牌只能在这里注入。
# 值来自项目根的 .env（docker compose 插值成容器环境变量），本脚本不含任何品牌默认值：
# 没配就是空字符串，页面上会显示成空白。空白一眼能看见，比悄悄用回旧值好排查。
# 字段清单和说明见项目根 .env.example 的「前端品牌」一段。
WEBROOT=/usr/share/nginx/html

# envsubst 不做任何转义，值里出现引号 / 反斜杠 / 尖括号会写坏 JS 字符串或 HTML 属性。
# 拦下来按空值处理，总比生成一个坏文件好。
# 值里的 $ 归 docker compose 管（插值阶段就会报错），这里拦不住也不用拦。
#
# 传了 html 就放宽：允许 < > "。目前只有页脚 SITE_FOOTER 用它 —— 那个值按 HTML 渲染，
# 要能写 <a href="...">。它只进 site-config.js 的 JS 字符串，不进 index.html 的属性，
# 所以尖括号伤不到别的字段。单引号/反斜杠依然不行：JS 字符串就是用单引号括的。
brand() {
    # $1=值  $2=变量名（只为了打日志）  $3=html 表示这个值要按 HTML 渲染
    case "$1" in
        *"'"*) BAD="单引号" ;;
        *\\*) BAD="反斜杠" ;;
        *'"'* | *'<'* | *'>'*)
            if [ "$3" = "html" ]; then BAD=""; else BAD="双引号或尖括号"; fi
            ;;
        *) BAD="" ;;
    esac

    if [ -n "$BAD" ]; then
        # 花括号不能省：$BAD 紧跟中文标点时，标点的首字节会被当成变量名的一部分吃掉
        echo "[品牌] $2 的值里有 ${BAD}，已按空值处理（该处会显示为空白）" >&2
        printf '%s' ''
    else
        printf '%s' "$1"
    fi
}

SITE_NAME="$(brand "${SITE_NAME:-}" SITE_NAME)"
SITE_SHORT_NAME="$(brand "${SITE_SHORT_NAME:-}" SITE_SHORT_NAME)"
SITE_SUBTITLE="$(brand "${SITE_SUBTITLE:-}" SITE_SUBTITLE)"
SITE_COLLEGE="$(brand "${SITE_COLLEGE:-}" SITE_COLLEGE)"
SITE_MAJOR="$(brand "${SITE_MAJOR:-}" SITE_MAJOR)"
SITE_FOOTER="$(brand "${SITE_FOOTER:-}" SITE_FOOTER html)"
# SEO 描述留空时取站名（唯一一处兜底）
SITE_DESCRIPTION="$(brand "${SITE_DESCRIPTION:-$SITE_NAME}" SITE_DESCRIPTION)"
export SITE_NAME SITE_SHORT_NAME SITE_SUBTITLE SITE_COLLEGE SITE_MAJOR SITE_FOOTER SITE_DESCRIPTION

# 白名单只列这 7 个 SITE_*，页面里别的 $ 一律不动。
# 先写 .tmp 再 mv：envsubst 中途失败也不会把 index.html 截断成半个文件
# （此时 nginx 还没启动，也不会有人请求到 .tmp）。
render_brand() {
    # $1=源文件  $2=输出文件
    if envsubst '${SITE_NAME} ${SITE_SHORT_NAME} ${SITE_SUBTITLE} ${SITE_COLLEGE} ${SITE_MAJOR} ${SITE_FOOTER} ${SITE_DESCRIPTION}' \
        < "$1" \
        > "$2.tmp"; then
        mv -f "$2.tmp" "$2"
    else
        rm -f "$2.tmp"
        echo "[品牌] 渲染 $2 失败，沿用镜像内置内容" >&2
    fi
}

# 渲染的源文件一律取 /etc/nginx/orig/ 里的原始副本，绝不拿上一次的结果再渲染一次。
# 理由和上面 nginx 模板的 .orig 完全一样，而且这里是实打实会出错的：
# 渲染过的文件里已经没有 ${SITE_*} 了，再渲染是空操作 —— 于是
# 「改了 .env 里的班名 → docker compose restart」时 index.html 原地不动，
# 而 site-config.js（每次从模板生成）变了，标签页标题和页面上的班名就对不上。
# 每次都从原始副本出发，渲染才真的幂等。
ORIG_DIR=/etc/nginx/orig

# site-config.js 不在镜像的 webroot 里，从模板现场生成
render_brand /etc/nginx/templates/site-config.js.template "$WEBROOT/site-config.js"
echo "[品牌] 已生成 $WEBROOT/site-config.js"

for BRAND_FILE in index.html manifest.webmanifest; do
    if [ -f "$ORIG_DIR/$BRAND_FILE" ]; then
        render_brand "$ORIG_DIR/$BRAND_FILE" "$WEBROOT/$BRAND_FILE"
        echo "[品牌] 已渲染 $WEBROOT/$BRAND_FILE"
    else
        echo "[品牌] 警告：$ORIG_DIR/$BRAND_FILE 不存在，跳过（$BRAND_FILE 保持镜像内置内容）" >&2
    fi
done

# ==================== 校徽 / PWA 图标：运行时替换 ====================
# 把图放进 data/frontend/branding/（容器内就是 /app/custom/branding/），重启前端容器即可：
#   branding/logo.png      顶栏、登录页、首页、关于班级的校徽
#   branding/favicon.png   标签页图标（只放 logo.png 时跟着用同一张）
#   branding/icons/*.png   PWA 图标 4 张 —— 容器里生成不了，要在本机先跑
#                          scripts/make_pwa_icons.py（见 README）
BRANDING_DIR=/app/custom/branding

# 先无条件还原成镜像内置的图。必须"无条件"：docker compose restart 不重建容器文件系统，
# 上次 cp 进去的自定义图会一直留着，"删掉自定义图再重启"就回不到内置校徽了。
# 逐个判断再拷：set -e 下一条 cp 失败会让容器起不来，宁可少还原一张图也不能这样
for IMG in logo.png favicon.png; do
    if [ -f "$ORIG_DIR/$IMG" ]; then
        cp -f "$ORIG_DIR/$IMG" "$WEBROOT/$IMG"
    fi
done
if [ -d "$ORIG_DIR/icons" ]; then
    mkdir -p "$WEBROOT/icons"
    cp -f "$ORIG_DIR/icons"/*.png "$WEBROOT/icons/" 2>/dev/null || true
fi

if [ -d "$BRANDING_DIR" ]; then
    for IMG in logo.png favicon.png; do
        if [ -f "$BRANDING_DIR/$IMG" ]; then
            cp -f "$BRANDING_DIR/$IMG" "$WEBROOT/$IMG"
            echo "[品牌] 已使用自定义 $IMG"
        fi
    done

    # 只放了 logo.png 时 favicon 跟着用同一张（这两张本来就是同一张图）
    if [ -f "$BRANDING_DIR/logo.png" ] && [ ! -f "$BRANDING_DIR/favicon.png" ]; then
        cp -f "$BRANDING_DIR/logo.png" "$WEBROOT/favicon.png"
    fi

    if [ -d "$BRANDING_DIR/icons" ]; then
        mkdir -p "$WEBROOT/icons"
        for IMG in "$BRANDING_DIR/icons"/*.png; do
            if [ -f "$IMG" ]; then
                cp -f "$IMG" "$WEBROOT/icons/"
                echo "[品牌] 已使用自定义 icons/$(basename "$IMG")"
            fi
        done
    fi
fi

exec "$@"
