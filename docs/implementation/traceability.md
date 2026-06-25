# 需求追踪矩阵

需求基线：[cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html)。

> 状态说明：`已验证` 表示当前仓库中有自动化测试或构建证据；`部分完成` 表示本地切片可运行但生产验收仍缺 live 环境、E2E、容量或安全证据。

| 需求编号 | 代码 / 契约 / 数据 | 当前证据 | 状态 |
|---|---|---|---|
| FR-IAM-001 | `services/api/src/cla/security.py`，`GET /api/v1/me` | API 测试覆盖开发 token、生产 JWKS/RS256、发现文档、错误 issuer/audience、过期 token、未知 kid 和缺失 bearer。 | 部分完成：外部校园 IdP smoke 未运行。 |
| FR-CONTENT-001 | `content/challenges/web-sqli-auth/manifest.yaml`，`packages/contracts/json-schema/challenge.schema.json`，`POST /api/v1/challenge-registry/import-local` | 题目 fixture 通过 JSON Schema；API 测试覆盖本地 Challenge 包导入、内容验证和 Registry 查询。 | 部分完成：生产内容 CI、镜像签名和大规模内容质量门禁仍未完成。 |
| FR-CONTENT-002 | `challenge_versions` 表、`challenge_artifacts` 表、seed 固定版本与摘要 | API 测试固定 `web-sqli-auth-001@1.3.0`；核心表契约覆盖 `challenge_versions`；Alembic 迁移覆盖 `challenge_artifacts`；导入测试验证对象资产引用。 | 部分完成：生产级对象生命周期、制品签名和远端 MinIO/S3 live 验证未完成。 |
| FR-CONTENT-003 | `services/api/src/cla/content_validation.py`，`Taskfile.yml`，教师验证报告页面 | 测试覆盖 schema/rubric、目标 HTTP smoke、Oracle 正负例、WARN/BLOCK 报告、教师审批门禁和页面构建；本机浏览器已验证教师验证报告页显示 Overall PASS、8 PASS、1 WARN、0 BLOCK。 | 部分完成：真实 OCI 构建、Trivy/SBOM、报告签名、Temporal 发布流程未完成。 |
| FR-AUTHOR-001 | `challenge_drafts`，`agent_runs`，`services/api/src/cla/authoring.py`，`services/api/src/cla/agent_runtime.py` | 测试覆盖教师 Brief 创建、幂等、模型解析 CourseIntent、模型失败回退、审计、Outbox 和 `AgentRun` 写入；本机 `.env` 已跑通 DeepSeek 兼容 live smoke，`brief.parse` 的 `AgentRun` 为 `SUCCEEDED` 且 `fallbackUsed=false`。 | 已验证本地模型适配链路；教师澄清 UI 和生产模型配额、限流、内容质量评测仍未完成。 |
| FR-AUTHOR-002 | `GET /api/v1/challenge-drafts/{id}/candidates`，`GET /api/v1/challenge-registry` | 测试覆盖硬过滤、候选理由、REMOTE_DESKTOP 冲突拒绝、BM25 风格全文检索、Registry 列表和对象资产展示。 | 部分完成：pgvector/OpenSearch 语义向量检索和大规模教学质量排序未完成。 |
| FR-AUTHOR-003 | `POST /api/v1/challenge-drafts/{id}/generate-version`，materialize 与 approve API | 测试覆盖模型生成题目版本草稿、Rubric 草稿、`PENDING_APPROVAL` 版本、验证报告、审批后发布、学生拒绝和审计；本机 live smoke 已验证 `generatedBy=model`、验证报告 `PASS`、教师审批后 `published=true`。 | 部分完成：Agent 能力 broker、Temporal 等待审批和多人审核策略未完成。 |
| 课堂题库发布层 | `challenge_bank_items` 表，`/api/v1/teacher/challenge-bank*`，`/api/v1/student/challenge-bank*`，`DELETE /api/v1/student/challenge-bank/{item_id}/environment`，`apps/web/components/TeacherWorkspaceShell.tsx`，`apps/web/components/TeacherChallengeBankPage.tsx`，`apps/web/components/TeacherChallengeCreatePage.tsx`，`apps/web/components/StudentChallengeBankPage.tsx` | `services/api/tests/test_challenge_bank.py` 覆盖教师创建草稿、发布、下架、修改、删除、回收站、恢复，学生题库可见性、时间窗口、同一学生同题 Attempt 幂等、不同学生同题独立 Attempt/LabSession、多题多 Attempt、学生销毁容器、未消费终端票据撤销、重新获取新 LabSession、目标地址返回和内部 route/sessiond 不泄露；Web typecheck 覆盖教师侧边栏题库、浮层详情、独立 Agent 创建页和学生题库销毁按钮。 | 已验证本地切片；生产 per-attempt HTTP 观测入口、外部 target URL 分配、真实编排销毁和大规模题库 UI 仍待后续实现。 |
| FR-ATTEMPT-001 | `POST /api/v1/assignments/{id}/attempts`，`idempotency_records` | `test_attempt_creation_is_idempotent` 覆盖重复 Idempotency-Key 返回同一 Attempt。 | 已验证本地切片。 |
| FR-LAB-001 | `lab_sessions`，LabSession CRD，environment-controller，路由注册与票据撤销 API | API、Go controller、fake-client、Kubernetes Event、orphan scanner、route registry、ticket revoke 和 metrics 测试均通过。 | 部分完成：真实 Kubernetes 集群写入、健康探针、TTL 清理、节点故障和 live orphan scan 未执行。 |
| FR-LAB-002 | `services/environment-controller/internal/labplan`，Helm/RBAC/CRD，NetworkPolicy | Go 测试覆盖 namespace、ResourceQuota、LimitRange、Secret、Service、NetworkPolicy、Deployment、安全上下文、gVisor runtimeClass 和禁止特权配置；静态测试覆盖 Compose/Helm。 | 部分完成：真实 NetworkPolicy、gVisor/Kata 节点兼容和跨 session 攻击测试未执行。 |
| FR-TERM-001 | 终端票据 API、内部 consume API、路由注册、`apps/web/components/TerminalWorkbench.tsx`、Gateway | API 测试覆盖 60 秒票据、单次消费、route/endpoint 不泄露、reset/unregister/revoke 后旧票据拒绝；Go Gateway 测试覆盖控制面消费；本机浏览器已验证 xterm.js 连接 Gateway/sessiond 并执行 `echo CLA_DEFAULT_TOKEN_OK`。 | 已验证本地浏览器切片；真实 Compose target 和生产集群路径仍未验证。 |
| FR-TERM-002 | Gateway 二进制协议、sessionwire、sessiond、重连缓冲、ACK 背压、Prometheus metrics | Go 测试覆盖 STDIN/STDOUT、resize、heartbeat、ACK、60 秒/1 MiB replay、Redis replay、背压窗口、Gateway metrics 和异步录制；本机浏览器重连后终端恢复 connected 并回显命令。 | 部分完成：live Redis/Compose 断线重连、指标 scrape/告警和跨网络浏览器断线 E2E 未执行。 |
| FR-TERM-003 | `runtime/shell-hooks/cla_bash_hook.sh`，`transcript_segments`，`services/api/src/cla/transcripts.py`，Gateway recording | API 测试覆盖语义事件、转录索引、本地 AES-GCM 加密、S3 fake client 后端、内部 API 上传/恢复/保留清理、bucket/prefix 绑定、OpenAPI 约束和敏感字段不泄露；Go 测试覆盖 Gateway 异步上传。 | 部分完成：live MinIO/S3、桶生命周期和生产恢复演练未执行。 |
| FR-EVENT-001 | `services/api/src/cla/events.py`，事件 JSON Schema，内部事件接入 | 测试覆盖事件追加、hash 链、stream waterline 和 batch 内序号唯一。 | 部分完成：高吞吐 gRPC ingest 未完成。 |
| FR-TUTOR-001 | `services/api/src/cla/tutor.py`，`stuck_assessments` | 测试覆盖重复失败命令、相同错误、长任务排除、跨学生拒绝、终端 prompt injection 不创建 AgentRun。 | 部分完成：模型边界案例和 precision/recall 标定未完成。 |
| FR-TUTOR-002 | Hint API、TutorPanel、independence index | 测试覆盖 L1-L3 主动求助、自动 L1、冷却、反馈、误判、关闭自动提示和独立完成指数。 | 部分完成：更大提示泄露 golden set 和 post-hint improvement 未完成。 |
| FR-MONITOR-001 | 教师 live monitor API 和页面 | 测试覆盖教师 RBAC、READY 统计、卡住统计、提示摘要、资源/安全告警计数和无原始终端文本泄露；本机浏览器已验证 live monitor 展示 1 个 Attempt、1 个 READY、0 个资源/安全告警。 | 部分完成：生产资源 telemetry 和 SSE 未完成。 |
| FR-GRADE-001 | `services/api/src/cla/oracle.py`，示例 Oracle | 测试覆盖坏签名拒绝和签名 Oracle 证据用于评分。 | 已验证本地切片。 |
| FR-GRADE-002 | Rubric、`services/api/src/cla/grading.py`，`criterion_results` | 测试覆盖 Oracle 和 EVENT_PATTERN 两类 CriterionResult 证据引用。 | 已验证本地切片；LLM_RUBRIC 未接入。 |
| FR-GRADE-003 | GradeRevision、CriterionResult、Appeal API、学生成绩页 | API 测试覆盖证据页数据、跨学生拒绝、申诉 criterion 校验、教师 override 生成新 revision；本机浏览器已验证成绩证据页、申诉创建、教师复核 API、Revision 2 和 `appeal:{id}` 证据引用。 | 部分完成：教师复核 UI 未完成。 |
| FR-ADMIN-001 | Feature flags、环境变量、Helm values | 静态测试覆盖 terminal-only Feature Flag 和 GUI 禁用。 | 部分完成：管理员管理 UI 和二次确认流程未完成。 |
| FR-EXT-001 | WorkspaceType enum、session endpoint | 测试覆盖 REMOTE_DESKTOP/SIMULATED 返回 `WORKSPACE_FEATURE_NOT_ENABLED`，并扫描一期无 GUI 依赖。 | 已验证本地切片。 |
| 工程文档与开发规范 | `README.md`，`docs/development/developer-guide.md`，`docs/development/architecture.md`，`docs/development/security.md`，`docs/development/testing.md`，`docs/development/git.md`，`docs/development/content-authoring.md`，`docs/runbooks/local-development.md` | 文档覆盖项目定位、模块职责、核心链路、安全边界、模型接入、题库 Registry、对象资产、测试矩阵、Git 协作、内容开发和本地运行；命名扫描和 Web 生成注释检查已通过。 | 已完成本轮文档交付。 |
| P0 契约与迁移 | JSON Schema、OpenAPI、Protobuf、Alembic | API 契约测试、OpenAPI route drift、核心表元数据、SQLite Alembic smoke 通过；PostgreSQL smoke 已接入 CI 配置。 | 部分完成：本地 PostgreSQL 未运行。 |
| P1 纵向核心 | 教师建作业/题库发布 → 学生 Attempt → Session/Ticket → Gateway → Event/Transcript → Oracle → Grade → Appeal → Monitor | API `70 passed, 1 skipped`；Go sessionwire/gateway/sessiond/controller 全部通过；Web build/typecheck 通过；本机浏览器已验证登录页样式、学生题库、Attempt、Lab Ready、xterm.js、命令回显、L1 提示、提交、成绩页、申诉、教师题库、教师验证报告和 live monitor。 | 部分完成：真实 Compose target/Oracle PASS、MinIO/Redis live 和生产集群 E2E 被 Docker/Kubernetes 环境不可用阻塞。 |

## 未标记完成的关键缺口

- Docker Compose 真实 lab 启动未运行。
- 浏览器连接 Gateway 的本机路径已运行；真实 target/Oracle PASS 和跨网络断线重连端到端路径未运行。
- live MinIO/S3、桶生命周期和对象恢复演练未运行。
- live Kubernetes controller、NetworkPolicy、gVisor/Kata 和 orphan cleanup 未运行。
- Temporal、生产告警 Dashboard、负载/混沌、安全攻防和 Agent 评测仍未完成。
