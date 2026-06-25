# CyberLab Assistant（CLA）终端优先网安实践平台

CyberLab Assistant（CLA）是面向高校网络安全课程的实践辅助系统。一期聚焦“真实隔离靶场 + 浏览器终端 + 过程辅助 + 证据化评分”，目标是让教师用 Challenge-as-Code 维护题目和作业，让学生在浏览器内通过 xterm.js 完成真实实验，让系统以外部 Oracle、事件证据和机器可读评分标准给出可复核成绩。

本仓库以 [cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html) 为需求、架构、安全和验收基线。任何后续开发都必须同时阅读规格文档、[docs/implementation/traceability.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/traceability.md) 和 [docs/implementation/status.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/status.md)，再开始修改代码。

## 当前状态

当前仓库已经实现 P0/P1 的本地纵向切片，但还不是完整生产靶场。

已具备自动化证据的能力包括：

- FastAPI 控制平面：开发 OIDC、生产 JWKS 验证路径、RBAC、课程、成员、作业、Attempt 幂等、LabSession、本地 reset、终端票据、路由注册、票据撤销、事件接入、转录索引、Oracle 观测、评分、申诉、Tutor 和教师监控。
- Challenge-as-Code：内置 `web-sqli-auth-001@1.3.0` 示例题，包含 manifest、topology、rubric、milestones、network/retention policy、target、workspace、Oracle 和验证报告。
- 契约制品：JSON Schema、OpenAPI、Protobuf、Alembic 迁移、LabSession CRD、Compose、Helm、OPA 策略骨架。
- Go 边界服务：`terminal-gateway`、`environment-controller`、`runtime/sessiond` 和共享 `sessionwire` 协议包。
- Web 前端：学生终端工作台、成绩证据页、教师题目验证报告页、教师 live monitor 页面。
- 证据化测试：API 测试、Go 单元测试、Web 构建与类型检查、Compose 配置解析均已执行通过。

仍未完成或未在真实环境验证的能力包括：

- 真实 Docker Compose lab build/up、浏览器连接 Gateway 的端到端 E2E、本地 MinIO/Redis live smoke。
- 真实 Kubernetes 集群中的 CRD/Helm apply、NetworkPolicy、gVisor/Kata、节点故障、TTL 和孤儿资源清理验证。
- Temporal 工作流生产化，目前 P1 使用同步确定性替代路径。
- 生产对象存储生命周期、恢复演练、容量、混沌、安全攻防和模型评测。
- 教师评分复核 UI、管理员策略 UI 和完整课程管理 UI。

## 阅读顺序

首次接手项目时按以下顺序阅读，避免只看局部代码后误判边界：

1. [cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html)：完整需求、安全约束、接口、验收和阶段目标。
2. [docs/implementation/status.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/status.md)：当前已经完成、已运行命令、已知限制和下一步。
3. [docs/implementation/traceability.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/traceability.md)：需求编号到代码、契约、测试和状态的映射。
4. [docs/user-manuals/teacher-guide.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/user-manuals/teacher-guide.md)：教师端题目维护、验证发布、作业监控、成绩证据和申诉复核使用说明。PDF 版本见 [output/pdf/cla-teacher-guide.pdf](/Users/fisherder/Desktop/研究生/Security_Class_Tool/output/pdf/cla-teacher-guide.pdf)。
5. [docs/user-manuals/student-guide.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/user-manuals/student-guide.md)：学生端浏览器终端、分级提示、答案提交、成绩证据和申诉使用说明。PDF 版本见 [output/pdf/cla-student-guide.pdf](/Users/fisherder/Desktop/研究生/Security_Class_Tool/output/pdf/cla-student-guide.pdf)。
6. [docs/development/developer-guide.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/development/developer-guide.md)：开发入口、模块职责、变更流程和代码规范。
7. [docs/development/architecture.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/development/architecture.md)：控制平面、实验平面、终端链路、内容链路和评分链路。
8. [docs/development/security.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/development/security.md)：不可突破的安全边界、秘密处理、Agent 能力边界和证据分级。
9. [docs/development/testing.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/development/testing.md)：不同变更类型必须运行的测试命令和验收口径。
10. [docs/development/content-authoring.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/development/content-authoring.md)：Challenge-as-Code、Oracle、Rubric 和内容验证规范。
11. [docs/development/git.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/development/git.md)：Git 初始化、提交、远程推送和协作规范。
12. [docs/runbooks/local-development.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/runbooks/local-development.md)：本地运行、本地账号登录、开发 token 和常见故障。

## 项目原则

CLA 的核心原则是“确定性系统负责事实和权限，Agent 只处理受限的歧义工作”。后续实现必须遵守以下规则：

- Agent Runtime 不得获得 Docker、Kubernetes、宿主 Shell、任意 SQL、任意 HTTP 或云管理员凭据。
- 浏览器不得获得 Pod 名称、容器 IP、Kubernetes 凭据、会话内部密码、`route_ref` 或 sessiond 地址。
- Terminal Gateway 不持有 Kubernetes 管理凭据，只通过 API 消费一次性终端票据并获得内部路由。
- `cla-sessiond` 运行在 workspace 容器内，以 non-root 用户创建受限 PTY，不访问控制平面，不评分，不部署，不重置。
- Shell hook、终端文本、附件和学生回答全部视为不可信输入，只能作为弱证据或辅助特征。
- 正式通过必须来自学生控制边界外的 Oracle 或平台签名事件，不能依赖容器内自报成功。
- 动态 Flag、Token、密码、Cookie、Authorization、模型密钥和 per-attempt secret 不得写入普通日志、Trace、Prompt、公开录制或题库索引。
- `REMOTE_DESKTOP` 和 `SIMULATED` 只保留类型和 Feature Flag，一期不得引入 GUI、RDP/VNC、Guacamole、桌面环境、视觉观察或模拟器运行依赖。

## 仓库结构

```text
.
├── apps/web/                         # Next.js 前端，学生/教师/管理端页面
├── services/api/                     # FastAPI 模块化单体，业务事实所有者
├── services/terminal-gateway/        # Go WebSocket 终端网关，负责票据消费和 PTY 中继
├── services/environment-controller/  # Go LabSession 控制器和 Kubernetes 资源规划
├── services/agent-runtime/           # Python Agent Harness 边界包
├── workers/temporal/                 # Temporal Worker 边界包
├── runtime/sessiond/                 # workspace 内 non-root PTY 服务
├── runtime/shell-hooks/              # 终端语义事件 hook
├── packages/contracts/               # JSON Schema、OpenAPI、Protobuf
├── packages/sessionwire/             # Gateway 与 sessiond 之间的二进制协议包
├── packages/policy-bundles/          # Agent 能力和高影响操作策略
├── content/challenges/               # Challenge-as-Code 示例题
├── content/validation/               # 题目验证报告
├── deploy/compose/                   # 本地 Compose
├── deploy/crd/                       # LabSession CRD
├── deploy/helm/cla/                  # Kubernetes Helm chart
├── docs/adr/                         # 架构决策记录
├── docs/development/                 # 面向开发人员和 agent 的工程文档
├── docs/implementation/              # 状态和需求追踪
├── docs/runbooks/                    # 运行手册
├── docs/user-manuals/                # 教师端和学生端使用手册，含 Markdown 与 HTML
└── output/pdf/                       # 编译生成的教师端和学生端 PDF 手册
```

## 主要服务职责

| 模块 | 当前职责 | 不允许做的事 |
|---|---|---|
| `services/api` | 领域事实、OIDC/RBAC、课程/题目/作业/Attempt、票据签发、事件接入、转录索引、Oracle、评分、申诉、审计和 Outbox | 不直接中继终端字节，不把容器内部状态当作正式成绩，不把秘密写入日志 |
| `services/terminal-gateway` | 消费一次性终端票据、连接 sessiond、WebSocket 二进制帧、resize、heartbeat、ACK、背压、重连 replay、异步录制 | 不持有 Kubernetes 管理凭据，不接受浏览器传入的容器地址，不执行命令 |
| `runtime/sessiond` | 在 workspace 容器内以 non-root 创建 PTY，接收 Gateway 的 stdin/resize，输出 PTY 字节 | 不访问 API 管理接口，不评分，不获取 Agent 工具，不持有集群凭据 |
| `services/environment-controller` | 规划 LabSession 命名空间、配额、NetworkPolicy、Service、Deployment、路由注册、票据撤销和孤儿扫描 | 不把普通 Docker 当作正式隔离边界，不创建 GUI 运行依赖 |
| `services/agent-runtime` | 受限 Agent Harness 边界，承载结构化输入输出和 Provider Adapter | 不持有基础设施管理员能力，不直接写业务数据库 |
| `apps/web` | 学生终端、提示、提交、成绩证据、教师验证和 live monitor 页面 | 不保存基础设施凭据，不展示 `route_ref`、容器 IP 或原始敏感终端内容 |

## 核心链路

### 教师出题和发布链路

1. 教师提交自然语言 Brief 和约束。
2. API 将 Brief 解析为结构化 CourseIntent。
3. 候选题按类别、目标、难度、时间、workspace 类型、隔离等级和允许工具进行硬过滤。
4. 教师选择候选题并 materialize 出不可变 ChallengeVersion。
5. 内容验证产生报告，包含 Schema、Rubric、目标服务 smoke、Oracle 正负例、策略和审批门禁。
6. 教师审批后 ChallengeVersion 进入可发布状态。

当前实现没有让 Agent 直接发布、部署或评分。后续接入模型时，模型输出必须经过结构化 Schema、教师审批和策略检查。

### 学生终端实践链路

1. 学生通过本地账号、OIDC 或开发 token 登录。
2. 学生对 Assignment 创建 Attempt，重复 `Idempotency-Key` 返回同一 Attempt。
3. API 创建或确认 LabSession，当前本地切片写入数据库和路由注册表。
4. 学生请求终端票据，API 签发 60 秒内有效的一次性 JWT，并登记 nonce。
5. 浏览器只拿到 `ticket` 和 `websocketUrl`。
6. Gateway 调用 API 内部 consume 端点，原子消费 nonce 并解析 session route。
7. Gateway 连接 sessiond，转发二进制 stdin/stdout、resize、heartbeat 和 ACK。
8. Gateway 异步把终端分片提交给 API，API 加密后写对象后端并记录索引。
9. Oracle 在学生控制边界外产生签名观测事件。
10. 学生提交解释后，评分器生成 GradeRevision 和 CriterionResult。
11. 学生查看证据页并可按 criterion 提交申诉。

### 评分和证据链路

当前评分支持确定性 Oracle 和事件模式两类证据。正式 CriterionResult 必须有证据引用、规则/评分器版本、分数、置信度和解释。后续接入 LLM_RUBRIC 时，模型只能评价开放性解释，不能覆盖客观 Oracle 事实，也不能独自判定纪律或作弊。

## 本地开发准备

推荐使用项目已有 `.venv`、本机 Go、Node 运行时和 pnpm。若当前机器没有依赖，先安装 Python 3.12、Go、pnpm 和 Docker Desktop 或 OrbStack。

常用环境变量：

| 变量 | 用途 | 本地默认 |
|---|---|---|
| `CLA_DATABASE_URL` | API 数据库连接 | `sqlite:///./cla-dev.db` |
| `CLA_DEV_MODE` | 开发 token 模式 | `true` |
| `CLA_LOCAL_AUTH_ENABLED` | 本地账号注册登录 | `true` |
| `CLA_LOCAL_AUTH_SECRET` | 本地账号会话 token 签名密钥 | `change-me-local-auth` |
| `CLA_GATEWAY_URL` | 浏览器连接的 Gateway 地址 | `ws://localhost:8081/ws/terminal` |
| `CLA_SESSIOND_ENDPOINT` | 本地 sessiond 地址 | `127.0.0.1:7777` |
| `CLA_INTERNAL_SERVICE_TOKEN` | 内部服务调用 token | `change-me-internal` |
| `CLA_TERMINAL_TICKET_SECRET` | 终端票据签名密钥 | `change-me-terminal-ticket` |
| `CLA_ORACLE_SHARED_SECRET` | Oracle HMAC 共享密钥 | `change-me-oracle` |
| `CLA_TRANSCRIPT_STORAGE_BACKEND` | 终端分片对象后端 | `local` 或 `s3` |
| `CLA_REMOTE_DESKTOP_ENABLED` | GUI 预留开关 | 必须为 `false` |
| `CLA_SIMULATED_WORKSPACE_ENABLED` | 模拟 workspace 预留开关 | 必须为 `false` |

## 常用命令

运行 API 测试：

```bash
.venv/bin/python -m pytest services/api/tests
```

运行 Go 测试：

```bash
env GOCACHE=/private/tmp/cla-go-cache /tmp/cla-go/go/bin/go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
```

如果系统 Go 已可用，也可以运行：

```bash
go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
```

运行 Web 构建和类型检查：

```bash
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
```

解析 Compose 配置：

```bash
docker compose -f deploy/compose/docker-compose.yml config
```

启动本地 API：

```bash
export PYTHONPATH=services/api/src
export CLA_DATABASE_URL=sqlite:///./cla-dev.db
export CLA_DEV_MODE=true
.venv/bin/uvicorn cla.main:app --reload --app-dir services/api/src
```

本地账号登录：

```text
http://localhost:3000/login
```

可以在登录页注册学生或教师账号。注册学生账号后进入学生工作台；注册教师账号后进入教师验证报告页。生产环境仍建议接入学校 OIDC，并由管理员审核教师身份。

生成开发 token：

```bash
PYTHONPATH=services/api/src .venv/bin/python -m cla.dev_tokens
```

执行 Alembic 迁移：

```bash
cd services/api
../../.venv/bin/python -m alembic upgrade head
```

验证内容包并重新生成教师报告：

```bash
PYTHONPATH=services/api/src .venv/bin/python -m cla.content_validation --output content/validation/web-sqli-auth-001-1.3.0.validation.json
```

## 开发规范摘要

- 所有项目文档、代码注释、任务说明、运行手册和 ADR 面向中文开发人员，默认使用中文。
- 文件、包名、环境变量、Header、指标、镜像和 Helm chart 使用 `cla` 或 `CLA`，不得引入历史旧名称。
- 修改任何领域模型、API 响应、事件、票据、Rubric、Challenge manifest 或 CRD 时，必须同步更新契约、测试、追踪矩阵和状态文档。
- 写 API 必须支持幂等或明确的乐观锁策略，并写入审计或 Outbox。
- 跨租户、跨课程、跨 Attempt 的授权检查必须在服务端完成，前端隐藏按钮不能视为权限控制。
- 终端、附件、学生答案、shell hook 输出和 target 返回内容全部按不可信数据处理。
- 任何新依赖进入生产路径前必须说明用途、权限影响、替代方案和回滚方式。
- 一期代码中不得加入 GUI 运行依赖或空服务来“占位”。只允许保留类型、接口和 Feature Flag。
- 测试必须说明真实执行结果。没有自动化或 live 证据的能力只能标为“部分完成”或“未验证”。

## 变更验收口径

最小验收集合：

```bash
.venv/bin/python -m pytest services/api/tests
env GOCACHE=/private/tmp/cla-go-cache /tmp/cla-go/go/bin/go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
docker compose -f deploy/compose/docker-compose.yml config
```

命名和中文化检查：

```bash
legacy_lower='z''y''a'
legacy_upper='Z''Y''A'
legacy_title='Z''y''a'
rg --hidden -n "${legacy_upper}|${legacy_lower}|${legacy_title}" . --glob '!.git/**' --glob '!node_modules/**' --glob '!apps/web/node_modules/**' --glob '!.pnpm-store/**' --glob '!apps/web/.next/**' --glob '!**/__pycache__/**' --glob '!*.pyc' --glob '!*.db'
find . -path './.git' -prune -o -path './node_modules' -prune -o -path './apps/web/node_modules' -prune -o -path './.pnpm-store' -prune -o -path './apps/web/.next' -prune -o -iname "*${legacy_lower}*" -print
```

这些检查返回空结果才符合当前命名要求。

## 文档维护规则

文档不是附属物。任何修改完成后都要检查：

- [docs/implementation/status.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/status.md) 是否记录了实际运行命令、结果、失败修复和已知限制。
- [docs/implementation/traceability.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/traceability.md) 是否把需求编号映射到新增或变更的代码、契约和测试。
- [docs/adr/](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/adr/) 是否需要新增或修改架构决策。
- [docs/runbooks/](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/runbooks/) 是否需要补充部署、恢复、排障或演练步骤。

## Git 与远程发布

本仓库可以初始化为普通 Git 仓库。首次提交前应确保 `.gitignore` 生效，不要提交 `.venv`、`node_modules`、`.next`、`__pycache__`、本地数据库、密钥和运行缓存。

推荐提交检查顺序：

```bash
git status --short
git add .
git status --short
git commit -m "docs: 完善 CLA 开发文档和项目规范"
```

远程 push 需要明确的远程仓库地址和权限。设置远程后再执行：

```bash
git remote add origin <REMOTE_URL>
git branch -M main
git push -u origin main
```

## 后续路线

优先补齐顺序：

1. 在可用 Docker daemon 上运行 Compose build/up，并完成本地 Gateway、sessiond、target、API、Web 的真实 E2E。
2. 接入浏览器 E2E：登录、Attempt、Lab Ready、xterm.js、curl、Oracle PASS、提交、成绩页、申诉。
3. 在 MinIO/S3 live 环境验证终端分片上传、恢复、保留清理、bucket policy 和生命周期。
4. 在开发 Kubernetes 集群验证 CRD/Helm、NetworkPolicy、gVisor/Kata、route registry、TTL 和 orphan cleanup。
5. 将本地同步 session lifecycle 和 grading orchestration 迁移到 Temporal Workflow/Activity。
6. 补齐生产观测 Dashboard、告警、容量、混沌、安全攻防和 Agent 评测。
