# 行迹 · XINGJI

**把一段旅行想法，变成一条可执行、可分享的路线。**

行迹是一个移动优先的 AI 旅行规划 Web App。用对话或表单说出城市、天数、同行人、兴趣、节奏和交通方式，它会结合高德的地点、开放时间与路线，在真实候选地点中排出 1–5 天行程；生成后可以继续编辑、查看地图、记录预算、分享给朋友，或邀请同行人一起修改。

- **地点有依据**：模型只在高德检索到的候选地点中筛选和排程，不编造地点；路线也通过高德实际查询，查询不到时显示未知，不用直线距离冒充路线。
- **结果可修改**：AI 生成只是起点，行程可以逐站拖动、调整时间并持久化保存，不是一段无法执行的文字。
- **分享有边界**：只读分享页不暴露对话、预算和待规划池；公开广场也只展示脱敏摘要。
- **本地轻量、生产可扩展**：本地开发默认 SQLite，生产使用 PostgreSQL 16，可按需接入 Redis。

[![CI](https://github.com/mochienwen-oss/xingji/actions/workflows/ci.yml/badge.svg)](https://github.com/mochienwen-oss/xingji/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-22.13%2B%20%7C%2024%2B-339933?logo=node.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)

## 界面预览

<p align="center">
  <img src="assets/screenshots/trip-desktop.png" alt="行迹行程工作台：地图路线与按天行程" width="100%">
</p>

| 探索与 AI 规划 | 移动端行程 | 只读分享 |
| :---: | :---: | :---: |
| <img src="assets/screenshots/explore-mobile.png" alt="探索与 AI 规划" width="240"> | <img src="assets/screenshots/trip-mobile.png" alt="移动端行程" width="240"> | <img src="assets/screenshots/share-mobile.png" alt="只读分享" width="240"> |

## 为什么做行迹

一次旅行规划，通常要在攻略、地图、备忘录和聊天群之间来回切换：

- **信息散**：景点、餐厅、开放时间和交通耗时分别散落在不同应用里。
- **排程难**：一天能去几个地方、顺序是否顺路、每段要多久，需要反复估算。
- **协作乱**：同行人改一版、自己改一版，最后不知道哪份是最新的。
- **预算事后才算**：行程确定后才发现交通和门票超支。

行迹把这条链路收进一个应用：说需求、生成行程、逐站修改、看地图和路线、记录花费、分享或协作，都在同一份行程里完成。

## 主要功能

### AI 行程规划

- 支持**对话输入**和**表单输入**。对话会识别目的地、天数、同行人数、兴趣、节奏、预算、必去地点和交通方式，并回填到表单，确认后再生成。
- 行程天数 **1–5 天**，同行人数 **1–20 人**，节奏为**轻松 / 适中 / 紧凑**，交通方式为**步行 / 驾车 / 公交**。
- 生成前先检索高德候选地点：优先核实必去地点和兴趣关键词，再补充景点、公园、博物馆等通用检索；地点不足或全部不在目标城市时会明确报错。
- 模型只从候选地点中选择，并按天、按停留时长排程；生成后查询相邻地点之间的高德路线。某天跨度过大或交通耗时过长时，预览会给出提示。
- **未登录可以预览**，但受匿名日配额限制；登录后才能保存到“我的行程”。

### 行程编辑

- 拖动调整地点顺序、修改停留时长（15–480 分钟）、删除地点，或把地点放回“待规划池”。
- 每天可以设置开始时间和希望结束时间；结束时间早于或等于开始时间时按次日计算。
- 可以为地点设置固定开始时间，并选择是否在次日；提前到达会计入等待，预计迟到会给出提示。
- 支持粘贴攻略文字：只抽取地点加入待规划池，或让 AI 按天整理成大纲，核对后一次采纳。
- 修改后点击“保存修改”才持久化；保存使用版本号做并发校验，别人已经保存过时会提示冲突，未保存的修改仍留在页面。
- 行程删除是软删除，分享链接立即不可访问；删除的行程进入回收站，可在 7 天内恢复。

### 地图、路线与附近探索

- 地点显示在高德 JS 地图上，点击地点列表可以定位到对应位置。
- 每天按顺序显示相邻路段，包含交通方式、预计耗时和高德返回的路线折线；地图服务暂时不可用时会保留已保存的地点信息并给出提示。
- 可以按天重新计算路线；调整顺序或停留时间后，未变化的路段会复用之前的结果。
- “附近探索”以已保存的行程地点为中心搜索餐厅、咖啡或景点，默认半径约 3 公里，可调整范围。
- “路线优化”会比较地图返回的交通耗时给出建议顺序，并避开与固定时间事项的冲突。

### 分享、协作与灵感广场

- **只读分享链接**：所有者可以生成分享链接，也可以撤销该行程的全部链接；一个行程同时只有一个有效链接。
- 分享落地页为 `/s/{token}`，打开不需要登录；链接失效或行程删除期间不可访问。
- 分享页只展示已保存的地点、活动、时间和路线，**不包含对话、预算和待规划池**。
- **8 位分享码**：朋友在“我的行程”输入分享码后成为可编辑协作者；分享码可以停用或轮换，所有者也可以移除协作者（移除后旧分享码失效）。
- 协作页面显示成员列表和当前在线人数，保存后其他人的页面会同步到新版本。
- **三级可见性**：私密、仅链接、公开。公开行程会出现在灵感广场，匿名可读；登录后可以复制一份到自己的行程，副本不包含原作者的 AI 对话。
- 公开行程和分享页都支持举报；运营侧可通过管理员接口查看举报列表。

### 预算与花费

- 创建者可以设置行程总预算；协作者也可以记录和编辑支出。
- 支出包含金额、分类（餐饮 / 交通 / 住宿 / 门票 / 其他）、日期、可选地点和备注。
- 页面展示总预算、已花费和剩余，可增删改每笔支出；删除后支持撤销恢复。
- 支持让 AI 根据当前行程估算花费；估算结果只是参考，不是报价。
- 预算和花费只在行程成员内可见，不进入只读分享页。

### 账号、安全与运营能力

- 注册要求用户名 2–80 字、密码 8–200 字，并同意服务条款；邮箱为选填。
- 登录失败默认累计 10 次后锁定 15 分钟，锁定期间即使密码正确也拒绝登录（`LOGIN_MAX_FAILURES` / `LOGIN_LOCK_SECONDS` 可调）。
- 会话使用 HttpOnly Cookie；生产 HTTPS 环境要求 Secure Cookie。登录后可以修改邮箱、修改密码、导出账号资料（含行程、预算和 AI 记忆）或注销账号。
- 配置 SMTP 后支持邮箱验证和找回密码；未配置时服务仍能启动，但邮件不会真正发出，页面会提示未发送。
- 账户设置里可以关闭“AI 记忆”；关闭后规划不再读取或写入长期偏好。
- 匿名访问有每日配额：默认 LLM 30 次、高德 300 次，登录用户不占匿名配额；另有独立的接口限流。
- 提供 `/api/health` 健康检查和 `/api/metrics` 只读观测快照；指标接口需要配置 `ADMIN_TOKEN` 并携带 `X-Admin-Token`。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | FastAPI、SQLAlchemy 2、LangGraph、langchain-openai、httpx、Alembic、psycopg3 |
| 前端 | React 19、Vite 6、TypeScript、dnd-kit |
| 数据 | 本地 SQLite（WAL）；生产 PostgreSQL 16；Redis 可选，用于跨 worker 的限流、匿名配额和实时在线名单 |
| 外部服务 | 高德开放平台（地点、详情、路线、地图）；OpenAI 兼容模型服务 |

调用链：浏览器 → FastAPI → LangGraph 规划/改稿流程 → 高德地点与路线 / 模型服务 → 归一化后存为行程 JSON。

## 安装

### 环境要求

- **Python 3.11 或更新版本**（CI 使用 Python 3.13）。
- **Node.js 22.13+ 或 24+**（见 `frontend/package.json` 的 engines）。
- **PostgreSQL 16**：生产/高并发环境需要；本地开发可不装，默认使用 SQLite。
- **高德开放平台**：Web 服务 Key、JS API Key、JS 安全密钥；按实际域名配置 JS Key 的安全域名。
- **模型服务**：支持 OpenAI Chat Completions 接口的模型及 API Key，或 DeepSeek API Key；模型需要支持 JSON 输出。
- 后端需要能访问高德和模型服务的网络。

### 1. 获取代码并安装后端依赖

```bash
git clone https://github.com/mochienwen-oss/xingji.git
cd xingji
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. 配置环境变量

复制示例配置，填写密钥；不要提交或分享 `.env`：

```powershell
Copy-Item .env.example .env
```

macOS / Linux 使用 `cp .env.example .env`。

至少需要填写：

| 变量 | 用途 |
| --- | --- |
| `AMAP_WEB_KEY` | 高德 Web 服务 Key，只在后端调用，用于地点搜索、详情和路线 |
| `AMAP_JS_KEY` | 高德 JS API Key，会下发到浏览器，用于地图 |
| `AMAP_JS_SECURITY_CODE` | 高德 JS 安全密钥，会下发到浏览器 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI 兼容模型网关；三者要么都填，要么清空 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | 未使用模型网关时使用 |
| `SESSION_SECRET` | 会话签名密钥；生产必须设置至少 32 字节的随机值 |

常用可选项：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串；不填则使用 `trip.db` |
| `APP_ENV` | `development` 或 `production` |
| `APP_BASE_URL` | 邮件和分享链接前缀；生产填写 `https://` 域名，不带结尾斜杠 |
| `COOKIE_SECURE` | 开发可为 `false`；生产使用 HTTPS 时必须为 `true`，或留空由 `APP_BASE_URL` 的 https 推导 |
| `REDIS_URL` | 需要多 worker 时配置，用于共享限流、匿名配额和在线名单 |
| `SMTP_*` | 邮箱验证和找回密码所需；不配置时服务仍能启动，但邮件不会发出 |
| `ADMIN_TOKEN` | 举报列表和 `/api/metrics` 的管理令牌；不配置时这些端点返回 404 |
| `ANON_LLM_DAILY` / `ANON_AMAP_DAILY` | 匿名日配额，设为 0 可关闭对应配额 |

生产（`APP_ENV=production`）会做启动校验：必须使用 PostgreSQL、必须提供 `SESSION_SECRET`、`APP_BASE_URL` 必须是 https 且不能是本机地址、`COOKIE_SECURE` 不能显式为 `false`。本地开发未设置 `SESSION_SECRET` 时，首次启动会生成仓库根 `.session-secret`（0600）复用。

#### 接入模型网关

如果模型网关提供兼容 OpenAI 的 `/v1/chat/completions` 接口，在 `.env` 中填写：

```dotenv
LLM_BASE_URL=https://llm-gateway.example.com/v1
LLM_API_KEY=在此填写完整密钥
LLM_MODEL=在此填写平台提供的准确模型名
```

`LLM_BASE_URL` 是接口基础地址，不包含 `/chat/completions`；实际路径以平台文档为准。启用该配置时必须同时填写密钥和模型名，不会自动借用 DeepSeek 密钥。清空 `LLM_BASE_URL` 可继续使用 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_MODEL`。修改 `.env` 后重启后端。

网关还需支持请求中的 `response_format={"type":"json_object"}`。配置正确仍无法生成时，请核实模型权限、可用额度和 JSON 输出支持。

### 3. 初始化账号并启动

使用 SQLite 本地开发可以直接运行：

```bash
python -m backend.create_user
```

按提示输入用户名和密码（密码不会显示）；需要更多账号时重复执行，也可以直接在网页注册。使用 PostgreSQL 时先完成下一节的迁移，再执行该命令。

构建前端并由后端托管：

```bash
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>。修改前端后重新运行 `npm run build` 并重启后端；没有构建产物时页面不可用。

### 4. 使用 PostgreSQL

PostgreSQL 的表结构只由 Alembic 管理，应用启动时不会自动建表。

```powershell
# 1. 准备 PostgreSQL 16 实例与账号（示例，按实际主机/密码替换）
psql -U postgres -c "CREATE ROLE trip LOGIN PASSWORD 'change-me';" -c "CREATE DATABASE trip OWNER trip;"

# 2. 让服务与迁移命令指向同一个库
$env:DATABASE_URL='postgresql+psycopg://trip:change-me@127.0.0.1:5432/trip'
python -m alembic upgrade head
```

把 `DATABASE_URL` 写进 `.env` 后重启服务。`APP_ENV=production` 且仍使用 SQLite 时，服务会按设计拒绝启动。默认仍是单进程 Uvicorn；设置 `REDIS_URL` 后，限流、匿名日配额和实时协同在线名单会改由 Redis 共享，可以开多个 worker；未配置或 Redis 连接失败时自动回退到进程内实现。

### 5. 前端开发模式

后端保持在 8000 运行，另开一个终端：

```bash
cd frontend
npm run dev
```

Vite 会把 `/api` 代理到本机 8000 端口，页面在 Vite 提供的地址打开。正式使用时仍建议构建后由 FastAPI 统一托管。

## 使用

### 生成第一份行程

1. 打开首页，选择“对话”或“表单”。
2. 对话可以直接说：“下周末去杭州玩两天，带父母，少走路，想去西湖和灵隐寺，预算 3000 左右。”页面会把识别出的城市、天数、人数、兴趣、预算和交通方式回填到表单，确认或修改后生成。
3. 未登录也可以预览；预览会展示每天的站点、停留时长、推荐理由、相邻路段耗时和路线。若提示跨度过大或某段交通过长，可以调整地点或交通方式后重试。
4. 登录后点击保存，行程进入“我的行程”，并分配真实行程 ID 和版本号。

### 编辑与保存

- 在行程工作台拖动地点调整顺序，或修改停留时长；也可以把地点移入“待规划池”，之后再安排到某一天。
- 为每天设置开始/结束时间，为需要准时到达的地点设置固定时间；结束时间早于开始时间会按次日计算。
- 点击“保存修改”。如果提示版本冲突，说明别人已经保存过，重新打开/合并后再保存；当前未保存的修改不会立刻丢失。
- 在 AI 对话里提出修改（例如“第二天少走一点，把博物馆换到上午”），AI 会先给出建议；应用后再保存。
- 需要整理攻略时，打开“导入攻略”，粘贴正文：可以只抽取地点加入待规划，也可以生成按天大纲并采纳。

### 地图、附近与预算

- 点击地点列表中的地点，可以在地图上定位；地图上会显示当天相邻地点的路线。
- “附近”以当前地点为中心搜索餐厅、咖啡或景点，选中后加入行程。
- “路线优化”会给出一版建议顺序；应用后仍需保存。
- 打开“预算”，设置总预算并记录支出；也可以让 AI 估算。金额在页面上按“元”输入。

### 分享、协作与公开

1. 行程所有者打开分享设置，生成只读链接；把链接发给朋友即可查看，不需要登录。撤销链接或删除行程后，旧链接立即失效。
2. 需要一起编辑时，生成 8 位分享码；朋友在“我的行程”输入分享码后成为协作者。页面上会显示在线人数，保存后其他人会同步到新版本。
3. 选择“公开”后，行程会出现在灵感广场；其他人登录后可以复制一份，副本不包含原作者的对话。
4. 分享页和公开行程都提供举报入口；被移除的协作者无法再用旧分享码加入。

### 账号与安全

- 在“我的”里登录/注册，或打开账户设置修改邮箱、密码、AI 记忆开关。
- 忘记密码时使用“找回密码”；只有配置了 SMTP 才会真正发送邮件。
- 账户设置支持导出 JSON（含行程、预算和 AI 记忆）以及注销账号；注销会永久删除账号、行程、协作与分享链接、预算和花费，无法恢复。
- 生产环境务必使用 HTTPS 和 Secure Cookie；不要把 `.env`、数据库文件或密钥提交到仓库。

## 项目结构

```text
backend/
  api/          HTTP 接口：认证、规划、行程、分享、预算、举报、健康检查
  services/     高德、模型、LangGraph 规划、路线优化、配额、分享快照
  db.py         数据模型与会话
  schemas.py    请求/响应类型
  main.py       应用初始化与路由注册
frontend/src/
  pages/        页面
  components/   地图、时间线、预算、攻略导入等组件
  lib/          接口工具
  types/        共享类型
  styles/       样式
alembic/        数据库迁移
scripts/        本地运行、预检与运维脚本
```

## 部署

可以在国内服务器上按上述方式安装，准备 PostgreSQL 16 并执行 `python -m alembic upgrade head`，构建前端后由 FastAPI 提供网页，再用 Nginx 反向代理到仅监听 `127.0.0.1:8000` 的服务，配置域名及 HTTPS；用系统服务管理器保持 Uvicorn 运行。

- 设置 `APP_ENV=production`、`APP_BASE_URL=https://你的域名`、`SESSION_SECRET`（至少 32 字节随机值）、`COOKIE_SECURE=true`。
- 配置高德 JS Key 的安全域名，并确认 Web 服务 Key 只出现在服务端。
- 数据库、`.env` 和访问日志放在服务器受限目录；不要提交 `.env`、`trip.db` 或真实密钥。
- 反向代理需正确传递 `X-Forwarded-Proto` / `Host`，并限制 `/docs`、`/api/metrics` 等调试/管理入口的访问范围。
- 使用 `GET /api/health` 做探活；需要观测时配置 `ADMIN_TOKEN`，再通过 `GET /api/metrics` 和 `X-Admin-Token` 读取只读快照。
- 实际部署、域名、证书及服务商账号需要使用者自行提供。

## 安全与数据

- `.env`、`.session-secret`、数据库文件和本地 HTTPS 证书不会进入 Git；高德 Web 服务 Key 只在后端使用。
- 会话使用 HttpOnly Cookie；生产环境要求 HTTPS 和 Secure Cookie；密码使用哈希存储。
- 分享 token 只保存哈希；只读分享页不包含对话、预算和待规划池。
- 账户支持导出资料和注销；注销会永久删除账号及关联数据，无法恢复。

## 已知限制

- 地点、开放时间和交通数据来自高德，并非对实际营业或出行时间的保证；缺失时显示未知。路线查询失败不会用直线代替。
- 预算用于偏好和记账，不是报价；预约、票价和开放时间请出行前向官方确认。
- 项目不抓取第三方攻略、不提供预订；攻略整理、分享、协作和灵感广场由用户主动输入或公开的数据构成。
- 模型只可选择地图候选地点，但生成结果仍需人工检查；路线、信息准确度和当地可用性依赖第三方服务。
- 分享页是只读的，不包含预算、AI 对话和待规划池；删除行程或撤销链接后旧链接不可用。
- 未配置 SMTP 时，邮箱验证和找回密码不会真正发信；未配置 Redis 时只能单进程运行；匿名配额和限流可能影响未登录试用。
- 图片、地点数据保存与传递给模型的用途应在上线前根据实际高德服务协议确认授权。
