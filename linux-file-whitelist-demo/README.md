# Linux File Whitelist Demo

一个面向 Linux 部署场景的微服务原型：

- 用户可通过网页提交设备白名单申请
- 管理员可在网页后台审核申请
- 审核通过后系统生成设备 `API Token`
- 设备程序可继续携带 Token 通过 API 上传
- 注册用户首次使用 Token 登录一次，之后通过 session cookie 进入共享空间
- 管理员文件空间与设备审核后台分离
- 每个文件可在 `public / registered / admin_only` 三种可见度之间切换
- 数据持久化使用 JSON 文件，便于直接 debug

## 技术选型

- Python 3.12
- FastAPI
- Jinja2
- JSON 文件存储（不使用 SQLite）
- Docker / Docker Compose

## 目录结构

```text
linux-file-whitelist-demo/
├── app/
├── data/
├── uploads/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 本地运行

```bash
cd /Users/robertgalvan/Documents/VibeCoding/Codexproject/linux-file-whitelist-demo
cp .env.example .env
bash start-linux.sh
```

打开：

- 公开主页: `http://localhost:8000/`
- 注册用户登录: `http://localhost:8000/workspace/login`
- 注册用户共享空间: `http://localhost:8000/workspace`
- 设备审核后台: `http://localhost:8000/admin/login`
- 管理员文件空间: `http://localhost:8000/admin/files`
- 公开下载页: `http://localhost:8000/downloads`

默认管理员密码来自环境变量 `ADMIN_PASSWORD`。

这个版本建议以单进程方式运行，避免多个 worker 同时写 JSON 文件。

## Docker 运行

```bash
cd /Users/robertgalvan/Documents/VibeCoding/Codexproject/linux-file-whitelist-demo
cp .env.example .env
docker compose up --build
```

建议在 `.env` 中至少修改：

```env
ADMIN_PASSWORD=your-admin-password
SESSION_SECRET=your-random-session-secret
```

## 上传接口

```bash
curl -X POST http://localhost:8000/api/upload \
  -H "Authorization: Bearer <API_TOKEN>" \
  -F "file=@/tmp/example.txt"
```

也支持：

```bash
curl -X POST http://localhost:8000/api/upload \
  -H "X-API-Token: <API_TOKEN>" \
  -F "file=@/tmp/example.txt"
```

## 权限分级

- 匿名访客: 可访问首页和公开下载页，只能下载 `public` 文件
- 注册用户: 首次用 API Token 登录一次后，浏览器通过 session cookie 保持登录，可进入共享空间上传和下载 `registered/public` 文件
- 设备程序: 继续通过 API Token 访问 `/api/upload`，默认上传为 `admin_only`
- 管理员: 审核设备申请、管理全部文件、实时调整每个文件的可见度

## 如何把地址告诉别人

假设你的 Linux 服务器 IP 是 `192.168.1.20`，那么可以这样分发入口：

- 白名单申请页: `http://192.168.1.20:8000/`
- 注册用户登录: `http://192.168.1.20:8000/workspace/login`
- 共享空间: `http://192.168.1.20:8000/workspace`
- 管理后台: `http://192.168.1.20:8000/admin/login`
- 管理员文件空间: `http://192.168.1.20:8000/admin/files`
- 公开下载页: `http://192.168.1.20:8000/downloads`

设备 API 上传地址：

```bash
http://192.168.1.20:8000/api/upload
```

注意：

- `0.0.0.0` 只是服务监听地址，不是发给别人的访问地址
- 对外分享时应使用服务器真实 IP 或域名

## JSON 数据结构

主数据文件默认为 [data/db.json](/Users/robertgalvan/Documents/VibeCoding/Codexproject/linux-file-whitelist-demo/data/db.json)。

包含三个顶层数组：

- `applications`: 白名单申请
- `devices`: 审核通过后生成的设备与 token
- `uploads`: 上传记录

这种结构适合小规模场景，直接打开 JSON 就能排查问题。

## 适用范围

当前实现适合：

- 不超过 6 个管理员/使用者
- 不超过 30 台设备
- 以局域网或受控网络环境为主
- 对“易部署、易调试”优先于复杂权限模型
- 单实例部署

## 后续可扩展建议

- 增加 Token 轮换
- 审核后台增加搜索和筛选
- 增加文件类型和大小策略
- 对接反向代理与 HTTPS
- 增加管理员账号体系
