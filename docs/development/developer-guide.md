# CLA 开发指南

本文面向后续人类开发人员和自动化开发 agent，说明 CyberLab Assistant（CLA）的工程入口、模块边界、代码规范、变更流程和文档维护要求。实施任何需求前，必须先阅读根目录 [README.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/README.md)、完整规格 [cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html)、状态文档和追踪矩阵。

## 开发前检查清单

每次开始开发前先确认：

1. 当前需求对应的规格章节和需求编号。
2. 相关代码模块、契约文件、数据库表、测试文件和部署文件。
3. 该需求是否会改变安全边界、权限模型、事件证据、终端票据、对象存储或评分结果。
4. 当前实现状态是否已经在 [docs/implementation/status.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/status.md) 记录。
5. 变更完成后需要更新哪些文档、测试、ADR 和追踪矩阵。

不要只看一个文件后直接实现跨边界功能。CLA 的核心风险来自权限、证据和隔离边界，必须先确认变更所在的信任平面。

## 命名规范

项目统一名称为 CyberLab Assistant（CLA）。

- 项目文档和注释使用中文。
- 包名、目录名、环境变量、Header、Helm chart、指标命名空间和对象前缀使用 `cla` 或 `CLA`。
- Python 包路径使用 `cla`、`cla_agent`、`cla_temporal`。
- Go module 使用 `cla-platform/...` 和 `cla.local/sessionwire`。
- 内部服务 Header 使用 `X-CLA-Service-Token`。
- Oracle 签名 Header 使用 `X-CLA-Oracle-Signature`。
- 不得新增历史旧项目名、旧缩写或旧路径。

每次较大修改后运行命名扫描：

```bash
legacy_lower='z''y''a'
legacy_upper='Z''Y''A'
legacy_title='Z''y''a'
rg --hidden -n "${legacy_upper}|${legacy_lower}|${legacy_title}" . --glob '!.git/**' --glob '!node_modules/**' --glob '!apps/web/node_modules/**' --glob '!.pnpm-store/**' --glob '!apps/web/.next/**' --glob '!**/__pycache__/**' --glob '!*.pyc' --glob '!*.db'
find . -path './.git' -prune -o -path './node_modules' -prune -o -path './apps/web/node_modules' -prune -o -path './.pnpm-store' -prune -o -path './apps/web/.next' -prune -o -iname "*${legacy_lower}*" -print
```

两个命令都应返回空结果。

## 模块边界

### `services/api`

API 是业务事实所有者，负责课程、成员、题目版本、作业、Attempt、LabSession、事件、转录索引、提示、评分、申诉、审计和 Outbox。API 直接持有数据库事务边界，也负责 OIDC 和 RBAC。

开发规则：

- 新写接口必须有权限检查。
- 修改数据的接口必须支持幂等、显式冲突处理或乐观锁策略。
- 业务事件必须包含 tenant、attempt/session 或领域对象上下文。
- 内部接口必须使用 `X-CLA-Service-Token`。
- 公开 API 不得返回 `route_ref`、sessiond endpoint、Pod 名称、容器 IP、Kubernetes Secret 或内部对象存储路径。
- 评分结果必须引用证据，不允许只返回模型自然语言结论。

常用文件：

- `services/api/src/cla/main.py`：FastAPI 路由和应用装配。
- `services/api/src/cla/models.py`：SQLAlchemy 领域模型。
- `services/api/src/cla/schemas.py`：Pydantic 请求和响应模型。
- `services/api/src/cla/security.py`：身份、RBAC 和错误格式。
- `services/api/src/cla/events.py`：事件追加、序号和 hash 链。
- `services/api/src/cla/tickets.py`：终端票据签发和消费。
- `services/api/src/cla/transcripts.py`：终端分片对象存储、加密、恢复校验和保留清理。
- `services/api/src/cla/oracle.py`：Oracle 签名验证。
- `services/api/src/cla/grading.py`：GradeRevision 和 CriterionResult。
- `services/api/src/cla/tutor.py`：卡住检测、提示和反馈。
- `services/api/src/cla/authoring.py`：教师 Brief、候选检索和内容验证入口。

### `apps/web`

Web 是浏览器体验层，当前包括学生工作台、成绩证据页、教师验证报告页和教师 live monitor 页面。

开发规则：

- 前端只消费公开 API，不直接调用内部接口。
- localStorage 只能保存开发 token 等本地调试数据，不能保存基础设施凭据。
- 终端连接只使用 API 返回的一次性 `ticket` 和 `websocketUrl`。
- 前端 UI 隐藏不是权限边界，所有敏感动作必须依赖 API 权限检查。
- 页面上不要展示原始终端敏感内容，教师监控默认展示摘要、计数和状态。

### `services/terminal-gateway`

Gateway 是终端字节中继和流控边界。它通过 API 消费终端票据，得到内部 `sessionRoute` 后连接 sessiond。

开发规则：

- Gateway 不持有 Kubernetes 管理凭据。
- Gateway 不接受浏览器提供的 sessiond 地址。
- 票据消费失败必须拒绝连接并计数。
- 二进制帧协议变更必须同步 `packages/sessionwire`、Web 端和测试。
- 高速输出必须受 ACK 背压控制，不能无限占用内存。
- 录制失败不得阻塞终端交互。

### `runtime/sessiond`

sessiond 位于 workspace 容器内，只负责创建 PTY 和转发字节。

开发规则：

- 进程必须拒绝 root 用户启动。
- 默认工作目录是 `/workspace`。
- 只接受 Gateway 协议帧，不接受业务控制命令。
- 不持有 API 管理 token、集群凭据、评分凭据或 Agent 工具权限。

### `services/environment-controller`

环境控制器负责 LabSession 的 Kubernetes 资源规划、调和和清理。

开发规则：

- 每个 session epoch 必须拥有独立命名空间或等价强隔离单元。
- 默认启用 Pod Security restricted、ResourceQuota、LimitRange、NetworkPolicy 和 RuntimeClass。
- 禁止 privileged、hostPath、hostNetwork、hostPID 和自动挂载 ServiceAccount token。
- route registry 由控制平面和 Gateway 消费，不暴露给浏览器。
- Reconcile 必须幂等，Finalizer 和 orphan scan 必须可重复运行。

### `services/agent-runtime`

Agent Runtime 是可替换的受限 Harness，用来承载 Brief 解析、候选重排、提示生成和开放答案评价等低信任能力。

开发规则：

- Agent 没有 Docker、Kubernetes、宿主 Shell、任意 SQL、任意 HTTP 或云管理员凭据。
- Agent 输出必须是结构化数据，并通过 Schema 校验。
- 高影响动作必须经过 Capability Broker、策略决策、审计和人工审批。
- Agent 不拥有业务事实，不直接写数据库。

### `content/challenges`

题目包采用 Challenge-as-Code。每个题目至少包含 manifest、topology、rubric、policy、workspace、target 和 Oracle。

开发规则：

- ChallengeVersion 一旦发布不可变，修改受控字段必须创建新版本。
- 镜像必须使用 digest 固定，生产发布前需要扫描、签名和 SBOM。
- Oracle 必须在学生控制边界外观察目标状态。
- Rubric 必须机器可读，每个 criterion 有明确证据要求。
- policy 必须声明网络、保留期、隔离等级和允许工具。

## 数据库开发规范

数据库迁移使用 Alembic。修改模型时必须同步：

1. `services/api/src/cla/models.py`
2. `services/api/alembic/versions/`
3. `services/api/tests/test_alembic_migrations.py`
4. 必要的 Pydantic schema 和 API 测试
5. 追踪矩阵和状态文档

领域建模规则：

- 所有跨租户对象必须包含 `tenant_id` 或通过父对象可严格推导 tenant。
- 课程成员和 Attempt 权限不得只靠前端过滤。
- Attempt 必须绑定不可变 ChallengeVersion、seed 和策略。
- GradeRevision 不覆盖历史版本，教师 override 生成新 revision。
- 事件只追加，关键事件使用 sequence 和 hash 链。
- Outbox 记录用于异步投递，消费者必须幂等。

## API 设计规范

公开 API 采用 `/api/v1` 前缀，内部 API 采用 `/internal` 前缀。

公开 API 要求：

- 请求和响应使用 Pydantic 模型。
- 错误格式包含稳定错误码，避免只返回自由文本。
- 写接口需要 `Idempotency-Key` 或明确解释为何不需要。
- 返回模型使用驼峰字段，内部 Python 可以使用蛇形字段。
- 不暴露基础设施内部细节。

内部 API 要求：

- 必须校验 `X-CLA-Service-Token`。
- 只面向 Gateway、Controller、Oracle、录制 worker 等可信部署单元。
- 失败必须可审计，不能静默降级为成功。

## 事件规范

事件是 Tutor、评分、审计和证据追溯的基础。

事件写入规则：

- 每个事件必须包含 attempt、session epoch、source、sequence、type、payload、occurred_at 和 hash。
- 同一 attempt、epoch、source 下 sequence 必须单调且唯一。
- 终端原始内容不应进入普通事件 payload；原始分片进入对象存储并只保存索引。
- 学生可控内容不得改变系统指令、工具权限或评分规则。
- 安全事件和策略拒绝事件要使用稳定 type，便于告警和教师监控。

## 终端协议规范

浏览器和 Gateway 使用 WebSocket 二进制帧：

- `CLIENT_STDIN`：浏览器输入。
- `CLIENT_RESIZE`：终端大小变化。
- `CLIENT_ACK`：浏览器确认服务端输出序号。
- `CLIENT_HEARTBEAT`：心跳。
- `SERVER_STDOUT`：Gateway 输出 PTY 字节。
- `SERVER_STATUS`：连接状态。
- `SERVER_REPLAY`：重连 replay 起止。
- `SERVER_ERROR`：稳定错误码。

任何协议变更必须同时修改：

- `apps/web/components/TerminalWorkbench.tsx`
- `services/terminal-gateway/internal/protocol/protocol.go`
- `services/terminal-gateway/cmd/gateway/*_test.go`
- 必要时修改 `packages/sessionwire`
- README 或开发文档中的协议说明

## 注释和文档规范

- 注释必须解释不明显的边界、约束、补偿逻辑或安全原因。
- 不写“把值赋给变量”这类重复代码含义的注释。
- 文档和注释默认中文。
- 引入新术语时先给中文解释，再保留英文简称。
- 修改行为后同步状态文档和追踪矩阵。
- 不能把未运行的能力写成“已完成”。

## 测试选择规则

变更越接近共享边界，测试越要完整：

- 只改文档：至少运行命名扫描，必要时运行相关渲染或格式检查。
- 改 API 路由、模型、权限、事件、评分、Tutor 或内容验证：运行 `services/api/tests`。
- 改 Gateway、sessiond、sessionwire 或 controller：运行 Go 测试。
- 改 Web：运行 Next build 和 typecheck。
- 改 Compose/Helm/CRD：运行 Compose config、静态测试和相关 Go/API 测试。
- 改安全边界：增加负例测试，并在文档中记录风险和验证证据。

完整测试要求见 [testing.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/development/testing.md)。

## 提交前检查

提交或交付前至少确认：

- 命名扫描无旧项目名残留。
- 文档和注释没有明显英文任务说明残留，专有名词除外。
- `.gitignore` 生效，未追踪 `.venv`、`node_modules`、`.next`、`__pycache__`、本地数据库和密钥。
- 相关测试已经运行并记录在状态文档。
- 追踪矩阵中对应需求状态没有被过度标记。
- 新增配置有本地默认值、生产建议值和安全说明。
