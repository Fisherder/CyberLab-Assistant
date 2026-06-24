# CLA 测试与验证指南

本文定义 CyberLab Assistant（CLA）的测试分层、命令、适用场景和验收口径。任何阶段性输出都必须记录真实运行命令和结果，不能用“理论可行”替代测试证据。

## 测试原则

- 越靠近安全边界，负例测试越重要。
- 越靠近共享契约，测试覆盖面越大。
- 没有真实运行证据的能力只能标记为“部分完成”或“未验证”。
- 自动化测试和 live smoke 要区分记录，不能把 fake client 结果当作真实集群验收。
- 测试失败先修复，不能通过放宽断言或删除测试掩盖问题。

## 当前已验证基线

最近一次完整本地验证结果记录在 [docs/implementation/status.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/status.md)。

当前已通过的主要命令：

```bash
.venv/bin/python -m pytest services/api/tests
env GOCACHE=/private/tmp/cla-go-cache /tmp/cla-go/go/bin/go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
docker compose -f deploy/compose/docker-compose.yml config
```

## 快速测试矩阵

| 变更类型 | 必跑测试 | 追加验证 |
|---|---|---|
| README、开发文档、ADR | 命名扫描；必要时查看链接和 Markdown | 若改命令或状态，运行对应命令 |
| API 路由、RBAC、领域逻辑 | `.venv/bin/python -m pytest services/api/tests` | 针对新接口增加正负例 |
| 数据库模型或迁移 | API 测试；Alembic smoke | 有 PostgreSQL 时运行 `CLA_TEST_POSTGRES_URL` 测试 |
| 事件、转录、Oracle、评分 | API 全量测试 | 增加证据缺失、坏签名、跨学生负例 |
| Tutor 或提示 | API 全量测试 | 检查 Prompt Injection 不创建 AgentRun |
| Gateway、sessionwire、sessiond | Go 测试 | live WebSocket smoke |
| Environment Controller | Go 测试；Compose/Helm 静态检查 | live Kubernetes apply 和 orphan scan |
| Web 页面或 API client | Web build；Web typecheck | 浏览器 E2E 或人工页面验证 |
| Compose、Helm、CRD | Compose config；相关 Go/API 静态测试 | 真实 Docker/Kubernetes smoke |
| 命名迁移 | 命名扫描；全量测试 | 检查文件名和路径 |
| 安全边界 | 对应单元/组件测试；新增负例 | 文档和 ADR 更新 |

## Python/API 测试

命令：

```bash
.venv/bin/python -m pytest services/api/tests
```

覆盖范围：

- OIDC 开发 token 和生产 JWKS/RS256 路径。
- RBAC、课程、成员、作业。
- Attempt 幂等。
- LabSession 本地创建、reset、路由注册和撤销。
- 一次性终端票据签发、消费、重放拒绝。
- 事件追加、序号、hash 链和 batch 约束。
- 终端转录索引、本地对象、fake S3、恢复校验和保留清理。
- Oracle HMAC 签名验证。
- GradeRevision、CriterionResult、Appeal 和教师 override。
- Tutor 卡住检测、提示、反馈和关闭自动提示。
- 教师验证报告和 live monitor。
- 契约 drift、JSON Schema fixture、Compose 约束和 GUI 禁用扫描。

新增 API 行为时，测试应包含：

- 授权成功路径。
- 缺 token、错误角色、跨租户或跨课程路径。
- 幂等重复调用或冲突处理。
- 审计或 Outbox 副作用。
- 返回体不泄露内部字段。

## Alembic 迁移测试

默认 SQLite smoke：

```bash
.venv/bin/python -m pytest services/api/tests/test_alembic_migrations.py
```

可选 PostgreSQL smoke：

```bash
CLA_TEST_POSTGRES_URL=postgresql+psycopg://cla:cla@localhost:5432/postgres \
  .venv/bin/python -m pytest services/api/tests/test_alembic_migrations.py
```

要求：

- 迁移能从空库升级到 head。
- 核心表存在。
- 生产 PostgreSQL 专属行为不要只用 SQLite 判断。
- 迁移失败不得被跳过，除非明确没有提供 PostgreSQL URL。

## Go 测试

如果使用仓库当前本地 Go 工具链：

```bash
env GOCACHE=/private/tmp/cla-go-cache /tmp/cla-go/go/bin/go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
```

如果系统 Go 可用：

```bash
go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
```

覆盖范围：

- `packages/sessionwire`：stdin、resize 帧编码和解码。
- `services/terminal-gateway`：票据消费、WebSocket 帧、heartbeat、resize、ACK、背压、replay、Redis replay、录制队列和指标。
- `runtime/sessiond`：non-root、PTY、sessionwire 读写。
- `services/environment-controller`：LabSession 类型、资源规划、fake client reconcile、route registry、ticket revoke、orphan scanner 和 Kubernetes Event。

新增 Gateway 或 sessiond 行为时，至少增加协议级或 handler 级测试，不能只靠人工连接。

## Web 构建和类型检查

命令：

```bash
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
```

注意：

- `next build` 会生成 `.next/types`。
- 不要并行运行 build 和 typecheck，以免 typecheck 读到正在重建的 `.next/types`。
- `apps/web/next-env.d.ts` 是 Next.js 生成文件，构建可能重写注释。

Web 修改要求：

- API 类型和字段必须与后端响应一致。
- 终端组件不能展示 route 或内部 endpoint。
- 页面不应在终端输入时抢焦点。
- 错误态、空态、加载态必须可读。

## Compose 验证

静态解析：

```bash
docker compose -f deploy/compose/docker-compose.yml config
```

live smoke，在 Docker daemon 可用时运行：

```bash
docker compose -f deploy/compose/docker-compose.yml build
docker compose -f deploy/compose/docker-compose.yml up
```

live smoke 应验证：

- Postgres、Redis、MinIO、API、Gateway、sessiond 和 target 能启动。
- API `/healthz` 正常。
- Gateway `/healthz` 正常。
- API 能连接数据库并执行迁移或初始化。
- Gateway 能消费 API 票据。
- sessiond 以 non-root 运行。
- target 只用于示例题，并能被 Oracle 观察。

当前已知限制：Docker daemon 曾不可用，因此 live Compose 未作为完成证据。

## Kubernetes 验证

静态文件：

- `deploy/crd/labsession-crd.yaml`
- `deploy/helm/cla/`
- `services/environment-controller/internal/labplan`

live 验证，在开发集群可用时执行：

```bash
kubectl apply -f deploy/crd/labsession-crd.yaml
helm upgrade --install cla deploy/helm/cla --namespace cla-system --create-namespace
```

必须验证：

- LabSession CRD 可创建。
- Controller reconcile 正常。
- 每个 session epoch 资源在独立命名空间。
- restricted Pod Security 生效。
- NetworkPolicy 默认拒绝。
- workspace 只能访问 target 所需端口。
- Gateway 能通过 route registry 连接 sessiond。
- reset 产生新 epoch，旧 route 和票据失效。
- TTL 和 orphan scanner 能清理残留资源。

生产验收前必须补充跨 namespace、跨 session 和横向移动负例。

## 内容验证

命令：

```bash
PYTHONPATH=services/api/src .venv/bin/python -m cla.content_validation --output content/validation/web-sqli-auth-001-1.3.0.validation.json
```

验证内容：

- manifest 符合 JSON Schema。
- rubric 符合 JSON Schema。
- topology、policy 和 milestones 可解析。
- target smoke 通过。
- Oracle 正例通过，负例拒绝。
- 验证报告可供教师页面读取。

生产内容 CI 还需要补：

- OCI build。
- 镜像扫描。
- SBOM。
- cosign 签名。
- 资源上限。
- 参考求解。
- 负例题解。

## 命名和中文化验证

命名扫描：

```bash
legacy_lower='z''y''a'
legacy_upper='Z''Y''A'
legacy_title='Z''y''a'
rg --hidden -n "${legacy_upper}|${legacy_lower}|${legacy_title}" . --glob '!.git/**' --glob '!node_modules/**' --glob '!apps/web/node_modules/**' --glob '!.pnpm-store/**' --glob '!apps/web/.next/**' --glob '!**/__pycache__/**' --glob '!*.pyc' --glob '!*.db'
find . -path './.git' -prune -o -path './node_modules' -prune -o -path './apps/web/node_modules' -prune -o -path './.pnpm-store' -prune -o -path './apps/web/.next' -prune -o -iname "*${legacy_lower}*" -print
```

文档和注释扫描可以辅助执行：

```bash
rg -n "^\\s*(#|//|/\\*|\\*)\\s*[A-Za-z]" . --glob '!node_modules/**' --glob '!apps/web/.next/**' --glob '!**/__pycache__/**' --glob '!*.pyc' --glob '!*.db' --glob '!pnpm-lock.yaml' --glob '!*.sum' --glob '!*.tsbuildinfo'
```

说明：

- 英文专有名词如 API、OIDC、Gateway、Oracle、Kubernetes、Temporal 可以保留。
- 任务描述、架构说明、注释、运行手册应以中文表达。
- 生成文件可能会被工具重写，必要时在状态文档中说明。

## 安全负例测试

安全变更必须考虑以下负例：

- 无 token、坏 token、过期 token、issuer/audience 错误。
- 学生调用教师接口。
- 跨学生读取成绩、申诉或 Attempt。
- 跨租户读取课程或对象。
- 终端票据重放。
- route unregister 后旧票据继续连接。
- Oracle 坏签名。
- shell hook 伪造通过。
- 终端文本 Prompt Injection 触发 AgentRun 或高影响操作。
- GUI Feature Flag 关闭时仍能进入 GUI workspace。
- Gateway 日志泄露终端 payload。

## 负载和混沌待办

以下测试尚未完成，不能作为已完成项描述：

- 100 并发学生终端连接。
- Gateway 故障和重连恢复 P95。
- Redis 变慢或不可用时 replay 降级。
- MinIO/S3 变慢、失败和恢复。
- Kubernetes 节点故障、Pod 驱逐和 orphan 清理。
- Temporal worker 重启和 Continue-As-New。
- 模型不可用时 Tutor 和开放评分降级。
- 安全攻防：SSRF、网络横向、容器逃逸尝试、Prompt Injection、Agent 越权。

## 记录测试证据

完成变更后更新 [docs/implementation/status.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/status.md)：

- 写明运行命令。
- 写明通过数量或失败信息。
- 写明失败是否已修复。
- 写明跳过原因。
- 明确未运行的 live 测试和阻塞原因。

更新 [docs/implementation/traceability.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/docs/implementation/traceability.md)：

- 将需求编号映射到代码、契约、测试和状态。
- 不要把 fake client、静态配置或单元测试夸大成生产验收。
