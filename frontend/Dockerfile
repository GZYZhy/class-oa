# 前端 Dockerfile（多阶段构建）
# 构建阶段
FROM node:20-alpine AS builder

WORKDIR /app

# 复制 package 文件
COPY package*.json ./

# 安装依赖
RUN npm config set registry https://registry.npmmirror.com && \
    npm install

# 复制源代码
COPY . .

# 构建
RUN npm run build

# 运行阶段 - 使用 nginx 提供静态文件
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置模板（启动时用 envsubst 生成实际配置）
RUN mkdir -p /etc/nginx/templates
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# 品牌配置模板：启动时由 docker-entrypoint.sh 用 envsubst 渲染成
# /usr/share/nginx/html/site-config.js（本地开发走 vite.config.js 里的同名插件，
# 读的是同一份模板，这样仓库里不用存第二份带值的副本）
COPY site-config.js.template /etc/nginx/templates/site-config.js.template

# 会被运行时改写的文件，各留一份原始副本到 webroot 之外。启动脚本一律从这份
# 原始副本出发去渲染 / 覆盖，绝不基于上一次的结果再来一次 ——
# docker compose restart 不重建容器文件系统，不这么做的话「改了 .env 重启」和
# 「删掉自定义校徽重启」都会沿用上一次的产物（和上面 nginx 模板的 .orig 是同一个坑）。
RUN mkdir -p /etc/nginx/orig/icons && \
    cp /usr/share/nginx/html/logo.png /usr/share/nginx/html/favicon.png /etc/nginx/orig/ && \
    cp /usr/share/nginx/html/icons/*.png /etc/nginx/orig/icons/ && \
    cp /usr/share/nginx/html/index.html /usr/share/nginx/html/manifest.webmanifest /etc/nginx/orig/

# 启动脚本：替换环境变量 → 生成 nginx 配置 → 启动 nginx
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# 暴露端口
EXPOSE 80
EXPOSE 443

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
