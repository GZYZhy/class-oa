# 后端 Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 设置环境变量
# TZ 需要配合下面的 tzdata 才生效，否则 datetime.now() 会返回 UTC，
# 和宿主机写入的记录差 8 小时（通知的「已于…更新」时间就是这样来的）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# 安装系统依赖（sqlite3 已内置在 Python 中；tzdata 提供时区数据库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
# 主源用清华镜像（国内快），加 --extra-index-url 指向官方 PyPI 作为兜底：
# 清华源偶尔会出现「某个版本同步丢了」的情况（比如 fastapi 0.115.0 就出现过），
# 有兜底源就不会因为一个包找不到导致整个构建挂掉
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --extra-index-url https://pypi.org/simple

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
