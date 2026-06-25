# CLA 本地开发运行手册

本文用于在本机运行和验证 CyberLab Assistant（CLA）一期终端切片。完整需求基线见 [cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html)。

## 本地环境要求

建议环境：

- Python 3.12。
- 项目根目录 `.venv`。
- Go 1.22 或仓库现有 `/tmp/cla-go/go/bin/go`。
- Node.js 与 pnpm。
- Docker Desktop 或 OrbStack，用于 Compose live smoke。
- 可选 Kubernetes 开发集群，用于 CRD/Helm live smoke。

如果只开发 API 或文档，不需要 Docker daemon。若要跑真实终端 E2E，需要 API、Gateway、sessiond、target 和 Web 同时可用。推荐直接使用本仓库的 tmux 重启脚本。

## 一键启动或重启本地服务

推荐方式：

```bash
chmod +x scripts/restart-local-dev.sh scripts/stop-local-dev.sh
scripts/restart-local-dev.sh
```

脚本会创建 `tmux -L cla-dev` 会话，并启动 5 个窗口：

| 窗口 | 服务 | 地址 |
| --- | --- | --- |
| target | 预置 Web SQLi 靶标 | `http://127.0.0.1:18080` |
| sessiond | 学生终端 PTY 服务 | `127.0.0.1:7777` |
| api | FastAPI 后端 | `http://127.0.0.1:8000` |
| gateway | 终端网关 | `http://127.0.0.1:8081` |
| web | Next.js 前端 | `http://127.0.0.1:3000` |

进入 tmux：

```bash
tmux -L cla-dev attach -t cla
```

停止整套本地服务：

```bash
scripts/stop-local-dev.sh
```

学生终端工作区默认会重建为 `/private/tmp/cla-local-workspace/web-sqli-auth`，内容来自 `runtime/sessiond/workspace-template/web-sqli-auth`。不要把学生工作区设置为 `/tmp` 或 `/private/tmp`，否则会把宿主临时目录暴露给学生。

## 环境变量

本地 API 常用变量：

```bash
export PYTHONPATH=services/api/src
export CLA_DATABASE_URL=sqlite:///./cla-dev.db
export CLA_DEV_MODE=true
export CLA_GATEWAY_URL=ws://localhost:8081/ws/terminal
export CLA_SESSIOND_ENDPOINT=127.0.0.1:7777
export CLA_INTERNAL_SERVICE_TOKEN=change-me-internal
export CLA_TERMINAL_TICKET_SECRET=change-me-terminal-ticket
export CLA_ORACLE_SHARED_SECRET=change-me-oracle
export CLA_TRANSCRIPT_STORAGE_BACKEND=local
export CLA_TRANSCRIPT_OBJECT_ROOT=/tmp/cla-transcript-objects
export CLA_REMOTE_DESKTOP_ENABLED=false
export CLA_SIMULATED_WORKSPACE_ENABLED=false
```

安全说明：

- 本地默认密钥只用于开发，不得进入生产。
- 生产必须使用 Secret 管理数据库、内部 token、Oracle secret、票据 secret 和对象存储凭据。
- `CLA_REMOTE_DESKTOP_ENABLED` 和 `CLA_SIMULATED_WORKSPACE_ENABLED` 在一期必须保持 `false`。

## 启动 API

```bash
export PYTHONPATH=services/api/src
export CLA_DATABASE_URL=sqlite:///./cla-dev.db
export CLA_DEV_MODE=true
.venv/bin/uvicorn cla.main:app --reload --app-dir services/api/src
```

健康检查：

```bash
curl http://localhost:8000/healthz
```

预期返回：

```json
{"ok":true,"agentRuntimeEnabled":false}
```

## 登录方式与开发 token

默认本地 Web 已提供注册和登录页面：

```text
http://localhost:3000/login
```

学生可以注册学生账号并进入学生工作台。教师可以注册教师账号并进入教师验证报告页。生产环境仍建议接入学校 OIDC，并由管理员审核教师身份。

开发 token 仍保留给自动化和底层接口调试使用：

```bash
PYTHONPATH=services/api/src .venv/bin/python -m cla.dev_tokens
```

脚本会输出教师和学生 token。使用 Web 工作台时，把学生 token 写入浏览器 localStorage：

```javascript
localStorage.setItem("claDevToken", "<student-token>")
```

也可以在本地验证时通过 URL hash 一次性写入，页面会读取后自动清理地址栏中的 token：

```text
http://localhost:3000/#claDevToken=<student-token>
```

教师页面使用教师 token：

```javascript
localStorage.setItem("claDevToken", "<teacher-token>")
```

开发 token 只在 `CLA_DEV_MODE=true` 时使用。本地账号登录由 `CLA_LOCAL_AUTH_ENABLED` 控制，默认开启。

## 执行数据库迁移

SQLite 本地开发默认由应用初始化表。需要显式执行 Alembic 时：

```bash
cd services/api
../../.venv/bin/python -m alembic upgrade head
```

PostgreSQL smoke：

```bash
CLA_TEST_POSTGRES_URL=postgresql+psycopg://cla:cla@localhost:5432/postgres \
  .venv/bin/python -m pytest services/api/tests/test_alembic_migrations.py
```

## 启动 Gateway

Gateway 需要 API 可访问。

```bash
cd services/terminal-gateway
CLA_API_URL=http://localhost:8000 \
CLA_INTERNAL_SERVICE_TOKEN=change-me-internal \
CLA_GATEWAY_ADDR=:8081 \
go run ./cmd/gateway
```

健康检查：

```bash
curl http://localhost:8081/healthz
```

指标：

```bash
curl http://localhost:8081/metrics
```

## 启动 sessiond

sessiond 必须以 non-root 运行。不要使用 root 或带特权的容器运行它。

```bash
cd runtime/sessiond
CLA_SESSIOND_ADDR=127.0.0.1:7777 \
CLA_WORKSPACE_SHELL=/bin/bash \
CLA_WORKSPACE_DIR=/private/tmp/cla-local-workspace/web-sqli-auth \
TARGET_BASE_URL=http://127.0.0.1:18080 \
go run ./cmd/sessiond
```

若看到 `cla-sessiond refuses to run as root`，说明当前用户是 root，应切换到普通用户。

若看到 `CLA_WORKSPACE_DIR must be a dedicated lab directory`，说明工作区被错误设置为宿主临时根目录。请改用专用目录，或直接执行 `scripts/restart-local-dev.sh`。

## 启动 Web

开发模式：

```bash
/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web dev
```

构建后 smoke 模式：

```bash
env CI=true NEXT_PUBLIC_CLA_API_BASE= CLA_API_INTERNAL_BASE=http://127.0.0.1:8000 \
  /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
cp -R apps/web/.next/static apps/web/.next/standalone/apps/web/.next/static
cd apps/web/.next/standalone/apps/web
HOSTNAME=:: PORT=3000 NEXT_PUBLIC_CLA_API_BASE= CLA_API_INTERNAL_BASE=http://127.0.0.1:8000 \
  node server.js
```

注意：standalone 服务必须从 `apps/web/.next/standalone/apps/web` 作为工作目录启动，并且要把 `apps/web/.next/static` 复制到该目录的 `.next/static`。否则浏览器会出现 chunk 404 或 `ChunkLoadError`。

默认访问：

```text
http://localhost:3000
```

Web 页面未登录时会自动跳转到 `/login`。登录成功后，页面会把会话 token 保存在浏览器本地存储中；点击“退出登录”会清除 token 并回到登录页。

## Compose 本地栈

解析配置：

```bash
docker compose -f deploy/compose/docker-compose.yml config
```

构建：

```bash
docker compose -f deploy/compose/docker-compose.yml build
```

启动：

```bash
docker compose -f deploy/compose/docker-compose.yml up
```

服务端口：

| 服务 | 端口 |
|---|---|
| API | `8000` |
| Gateway | `8081` |
| Postgres | `5432` |
| Redis | `6379` |
| MinIO API | `9000` |
| MinIO Console | `9001` |
| 示例 target | `18080` |

注意：Compose 只用于可信本地开发，不能承载不可信学生正式实验。

## 运行测试

API：

```bash
.venv/bin/python -m pytest services/api/tests
```

Go：

```bash
env GOCACHE=/private/tmp/cla-go-cache /tmp/cla-go/go/bin/go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
```

Web：

```bash
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
```

内容验证：

```bash
PYTHONPATH=services/api/src .venv/bin/python -m cla.content_validation --output content/validation/web-sqli-auth-001-1.3.0.validation.json
```

## 手动纵向验证路径

在 API、Gateway、sessiond 和 Web 都启动后：

1. 打开 `http://localhost:3000/login`。
2. 注册或登录学生账号。
3. 进入学生工作台。
5. 点击开始，创建 Attempt 和 LabSession。
6. API 返回一次性终端票据，Web 建立 WebSocket。
7. 在终端中执行命令。
8. 提交解释。
9. 查看成绩证据页。
10. 提交申诉。
11. 教师打开 `/teacher/challenges/cv_web_sqli_auth_1_3_0/validation` 查看验证报告。
12. 教师打开 `/teacher/assignments/asg_web_sqli_auth/live` 查看 live monitor。
13. 教师通过 `/api/v1/appeals/{appeal_id}/resolve` 复核申诉，确认生成新的 GradeRevision。

如果 Gateway 显示票据拒绝，检查：

- API 是否正在运行。
- `CLA_INTERNAL_SERVICE_TOKEN` 是否一致。
- 票据是否超过 60 秒。
- 是否重复使用同一个 nonce。
- reset 后是否仍使用旧票据。

## 常见问题

### API 启动后没有种子数据

确认：

- `CLA_DATABASE_URL` 是否指向预期数据库。
- 是否删除过 `cla-dev.db`。
- `seed_dev_data` 是否执行。

可重新删除本地数据库后启动 API。注意本地数据库被 `.gitignore` 忽略，不应提交。

### Web typecheck 报 `.next/types` 缺失

先运行 build，再运行 typecheck。不要并行运行二者。

```bash
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
```

### Compose 不能连接 Docker daemon

确认 Docker Desktop 或 OrbStack 正在运行。若当前环境没有 daemon，只能运行静态 `docker compose config`，不能把 live Compose 标记为已验证。

### Gateway 无法连接 sessiond

检查：

- sessiond 是否监听 `127.0.0.1:7777`。
- API 中 LabSession 的 `route_endpoint` 是否匹配。
- reset 后是否刷新了 session epoch。
- 防火墙或容器网络是否阻断。

### Oracle 观测被拒绝

检查：

- `CLA_ORACLE_SHARED_SECRET` 是否一致。
- payload 是否按规范 JSON 计算签名。
- `targetSessionKey` 是否匹配当前 Attempt。
- `X-CLA-Oracle-Signature` Header 是否存在。

### 终端没有输出

检查：

- WebSocket 是否连接。
- Gateway 是否收到 `SERVER_STATUS=CONNECTED`。
- sessiond 是否成功启动 shell。
- 浏览器是否发送 binary frame。
- Gateway 指标中的 terminal bytes 是否增加。

## 上课前必须检查

正式上课或演示前至少检查：

- `CLA_REMOTE_DESKTOP_ENABLED=false`
- `CLA_SIMULATED_WORKSPACE_ENABLED=false`
- Gateway 通过票据消费接口解析路由。
- 浏览器响应不包含 route、Pod 名称、容器 IP 或 sessiond 地址。
- sessiond 以 non-root 运行。
- Oracle 观测带签名。
- 终端录制故障不影响终端。
- Agent Runtime 关闭时终端和客观评分仍可运行。
- 状态文档记录了本次实际运行命令和结果。
