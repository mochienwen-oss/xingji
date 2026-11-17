# 更新日志

本文件记录面向使用者和部署者的版本变更；详细审计与修复记录保留在内部开发资料中。

## 0.3.0 - 2026-11-15

全项目审计后的版本更新，统一前后端版本号，并集中修复一批一致性、可靠性和可维护性问题。

### 版本

- 后端新增 `backend.__version__`，与 `frontend/package.json`、`frontend/package-lock.json`、`frontend/src/lib/appInfo.ts` 保持一致。
- `GET /api/health` 的 200/503 响应新增 `version` 字段，便于确认实际部署版本；行为仍为只读、不鉴权、不限流。
- 新增跨来源版本一致性测试 `tests/test_version.py`。

### 后端

- 修复规划场景缺失时回退消息覆盖动态 JSON 的问题。
- 过期数据清理移出请求路径，改为启动清理加每小时后台任务，避免请求内全表扫描。
- `users.email` 的 ORM 唯一约束与 Alembic 部分唯一索引对齐。
- 注销账号时解除 `trip_reports` 的举报人引用；补充分享链接、分享码、恢复、协作者、支出、导出等接口的限流覆盖。
- 分享快照缓存命中时也执行裁剪，避免缓存无限增长。
- 统一分享/邀请/账号 token 与会话 cookie 的公共实现，收拢请求模型与重复的地点查询/刷新逻辑。
- 修正 `APP_BASE_URL` 多处读取、邮件/分享页基础地址和 `last_edited_at` 时间精度不一致。

### 前端

- 修复邀请接受失败后重试不重新执行的问题，并区分 409/410/422/503 文案。
- 修复 SSE 流尾部半帧丢失、hash 路由重复派发，以及草稿每次键入都全量写 localStorage 的问题。
- 实时协同时在线状态由 WebSocket 承载时停止 10 秒轮询，断线或退出后恢复；今日行程缓存增加日期守卫。
- 对话记录改为 `role="log"`，避免读屏器逐 token 朗读。
- 合并重复的 Haversine、地图加载、颜色与焦点/拖拽工具，删除死代码和无效样式，补充可复用的无障碍隐藏类。

### 仓库与文档

- 清理无引用探针、截图、日志和残留审计文件，修正 `.gitignore`、`.env.example`、README 与运维文档中的过时说明。
- 预检脚本增加 `COOKIE_SECURE` 与多 Alembic head 检查，并补充对应测试。

### 验证

- 后端：586 passed, 1 skipped；`pyflakes backend scripts tests alembic` 无输出。
- 前端：52 个测试文件、402 个测试通过；`npm run typecheck`、`npm run build` 通过。
- 数据库迁移 head 为 `0009_cleanup_dead_schema`。
- 另以 PostgreSQL 16 实测 0.2.x 数据从 `0006_analytics_daily` 增量升级到 head：迁移、数据保留与回滚/重升级均通过。
