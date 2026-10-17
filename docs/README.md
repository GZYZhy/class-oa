# 文档

| 文档 | 给谁看 | 内容 |
|---|---|---|
| [使用手册](guide.md) | 同学、班委、管理员 | 登录、通知、投票、办件、名单、考勤、成绩、系统管理 |
| [部署与运维](serve.md) | 部署与维护者 | 环境要求、部署、初始化、反向代理、升级回滚、备份、安全、排错 |

其他入口：

- [README](../README.md)：项目简介与快速开始
- [.env.example](../.env.example)：全部环境变量与逐项说明
- [docker-compose.yml](../docker-compose.yml)：部署编排文件

## 本地开发

```bash
# 后端（http://localhost:8000）
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload

# 前端（http://localhost:5173）
cd frontend && npm install && npm run dev
```

## 测试

```bash
./runTest.sh          # 一键跑完后端 + 前端，并打印简报
```

后端每个用例都会起一次真实后端进程并创建临时数据库，不会读写 `data/` 里的数据；
前端用 Vite 的 SSR 管道真实渲染组件并断言页面文案。
