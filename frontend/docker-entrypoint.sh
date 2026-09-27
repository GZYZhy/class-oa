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

        proxy_connect_timeout 60s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;

        add_header Cache-Control \"no-store\";
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

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control \"public, immutable\";
    }

    gzip on;
    gzip_min_length 1k;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/javascript application/json application/javascript application/xml;
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

exec "$@"
