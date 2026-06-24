# CLA 安全开发规范

本文定义 CyberLab Assistant（CLA）一期终端实践平台的安全边界和开发约束。任何代码、配置、文档或部署修改都不能降低这些约束。若实现方式必须变更，需要新增 ADR 并补充负例测试。

## 安全目标

CLA 的安全目标不是“学生永远无法在容器里做坏事”，而是：

- 学生不能跨 Attempt、课程、租户或会话访问他人数据和环境。
- 学生不能通过浏览器、终端、附件、target 输出或回答影响系统指令、评分规则、工具权限或部署权限。
- Agent 不能获得基础设施管理员能力。
- 终端实践不因为 Tutor、Agent、shell hook 或录制组件故障而不可用。
- 评分证据可追溯、可复核、可申诉，且不能由学生在 workspace 内自报伪造。
- 动态秘密不进入普通日志、Trace、Prompt、题库索引或公开录制。

## 信任边界

| 数据来源 | 信任级别 | 处理规则 |
|---|---|---|
| OIDC/JWKS | 高，仍需校验 | 校验 issuer、audience、alg、kid、exp 和签名 |
| API 数据库 | 业务事实 | 通过事务、RBAC、审计和迁移维护一致性 |
| Gateway consume 结果 | 内部可信 | 只通过 `X-CLA-Service-Token` 获得 |
| Oracle 签名观测 | 评分高证据 | 必须验证 HMAC 和 payload 规范化 |
| 终端 stdout/stdin | 学生可控 | 只作为弱证据或转录对象，不能直接决定通过 |
| shell hook 事件 | 学生可影响 | 用于辅助和弱证据，不作为唯一正式通过依据 |
| target HTTP 响应 | 学生可能间接影响 | Oracle 可读取，但要在学生控制边界外运行 |
| 学生答案 | 不可信自然语言 | 只能作为开放答案输入，不得改变系统指令 |
| Agent 输出 | 低信任建议 | 必须结构化、校验、审计，不能直接执行高影响动作 |

## 身份和授权

API 必须在服务端完成授权：

- 所有公开 API 都要认证，除 `/healthz` 等明确公开探针外。
- 用户通过 OIDC subject 映射到平台 `User`。
- 租户必须贯穿查询条件或通过父对象严格推导。
- 教师只能管理所属课程。
- 学生只能创建和查看自己的 Attempt、成绩和申诉。
- TA 权限需要显式定义，不得自动等同教师。
- 内部 API 使用 `X-CLA-Service-Token`，不能复用学生 token。

负例测试必须覆盖：

- 跨租户读取课程、作业、Attempt、成绩和转录索引。
- 学生调用教师接口。
- 教师访问不属于自己课程的学生 Attempt。
- 伪造内部服务 token。

## 终端票据安全

终端票据是浏览器进入 Gateway 的唯一凭据。

票据必须包含：

- `iss=cla-api`
- `aud=cla-terminal-gateway`
- `sub`
- `tenant_id`
- `attempt_id`
- `session_id`
- `session_epoch`
- `route_ref`
- `permissions`
- `nonce`
- `iat`
- `exp`

实现要求：

- 票据有效期默认 60 秒。
- nonce 创建时为 `ISSUED`，内部 consume 后原子更新为 `CONSUMED`。
- 重放同一 nonce 必须失败并写审计。
- reset、新 epoch、route unregister 或 revoke 后旧票据必须失败。
- Web 响应不得包含 `route_ref`、endpoint、Pod 名称或容器 IP。
- Gateway 必须调用 API consume，不得本地自行解析 route。

## Gateway 安全边界

Gateway 的职责是字节中继和流控，不是环境控制器。

禁止事项：

- 禁止持有 Kubernetes 管理凭据。
- 禁止执行 `kubectl exec` 或宿主命令。
- 禁止接受浏览器提供的内部 endpoint。
- 禁止把终端 payload 写入普通日志。
- 禁止因为录制失败断开正常终端实践。

必须事项：

- 票据消费失败返回稳定拒绝。
- WebSocket 连接关闭时释放连接和指标。
- replay buffer 有时间和大小上限。
- 背压按 ACK 控制未确认字节。
- 异步录制队列满时应降级并计数，而不是阻塞交互。

## sessiond 安全边界

`cla-sessiond` 位于实验 workspace 内。它与学生进程处在同一敌对平面，因此能力必须极小。

要求：

- 以 non-root 用户运行。
- root 启动时直接拒绝。
- 只监听 sessionwire 协议端口。
- 默认工作目录为 `/workspace`。
- 不挂载控制平面 token。
- 不读取 Kubernetes Secret。
- 不包含评分、部署、重置或 Agent 调用逻辑。

## 实验隔离

生产实验环境必须使用 Kubernetes 和容器隔离增强能力。普通共享 Docker 只允许用于可信本地开发。

Kubernetes 目标约束：

- 每个 session epoch 独立命名空间。
- 命名空间启用 restricted Pod Security enforce、audit 和 warn。
- ResourceQuota 限制 pods、CPU、内存和临时存储。
- LimitRange 设置默认 request 和 limit。
- 默认拒绝 ingress 和 egress。
- 只允许 Gateway 命名空间访问 workspace sessiond。
- 只允许 workspace 访问 target 所需端口。
- 默认 RuntimeClass 为 gVisor。
- 高风险 Pwn/调试题必须单独验证 Kata 或专用节点池。
- 禁止 privileged、hostPath、hostNetwork、hostPID。
- 禁止自动挂载 ServiceAccount token。

测试要求：

- 静态规划测试必须断言禁止项不存在。
- live 集群测试必须验证 NetworkPolicy 和跨 session 隔离。
- orphan scanner 必须在异常删除、节点故障或 controller 重启后可回收资源。

## Oracle 安全边界

正式客观通过必须来自外部 Oracle 或平台签名事件。

Oracle 要求：

- 在学生控制边界外运行。
- 观察 session-specific target 状态。
- 使用共享密钥或更强签名机制。
- payload 规范化后验签。
- 观测事件写入 `oracle.observed` 等稳定事件类型。
- 签名失败、过期、session key 不匹配或 payload 缺字段必须拒绝。

禁止事项：

- 禁止用 workspace 内某个学生可写文件作为唯一通过依据。
- 禁止让学生直接提交“我通过了”的事件。
- 禁止让 Agent 覆盖客观 Oracle 结果。

## Agent 能力边界

Agent 是辅助组件，不是系统主干。

Agent 禁止获得：

- Docker socket。
- Kubernetes kubeconfig 或 ServiceAccount 管理 token。
- 宿主 Shell。
- 任意 SQL。
- 任意 HTTP 出网。
- 云管理员凭据。
- 评分发布权限。
- 题目发布最终审批权限。

Agent 允许的能力必须通过白名单：

- `content.search`
- `schema.validate`
- `rubric.draft`
- `hint.generate`
- `answer.evaluate`

所有 Agent 输出必须：

- 有输入 Schema、输出 Schema、Prompt 版本、模型版本和工具版本。
- 通过结构化校验。
- 写入 AgentRun 或等价审计记录。
- 对高影响建议要求教师审批或 deterministic service 复核。

Prompt Injection 防护要求：

- 来自终端、附件、网页、学生答案和 target 的自然语言永远不能提升权限。
- Prompt 中不得包含动态 Flag、Token、Cookie、Authorization 或教师解法。
- 模型不可用时，核心终端和客观评分仍可运行。

## 秘密和日志

动态秘密包括：

- per-attempt flag、session key、target password、cookie、token、Authorization header。
- OIDC/JWT secret。
- Oracle shared secret。
- terminal ticket secret。
- internal service token。
- transcript encryption key。
- cloud key、registry token、database password。

处理规则：

- 不写普通日志。
- 不写 Trace 标签。
- 不写 Prompt。
- 不写公开录制。
- 不写题库索引。
- 不返回到前端，除非该前端明确属于授权学生并且该值是题目设计的一部分。
- 配置文件只能放本地开发默认值，生产使用 Secret 管理。

## 转录隐私

终端录制用于恢复、证据和排障，但隐私风险高。

要求：

- 原始终端分片加密后写对象存储。
- 数据库只保存对象引用、hash、方向、序号范围和脱敏状态。
- 恢复校验不返回明文。
- 教师监控默认不展示原始终端文本。
- 保留期按课程策略和最小化原则执行。
- 删除失败要返回明确错误，不能标记为已清理。

## 评分和申诉安全

评分必须可追溯：

- GradeRevision 不可变。
- CriterionResult 必须有 evidence_refs。
- 教师 override 生成新 revision，不覆盖旧 revision。
- 申诉记录提交者、criterion、理由、状态、处理者和处理时间。
- 自动评分低置信或证据缺失时进入人工复核。

禁止事项：

- 禁止无证据给分。
- 禁止模型单独判定作弊。
- 禁止学生通过修改终端事件获得客观通过。
- 禁止把申诉处理直接改写历史成绩。

## 安全变更流程

任何涉及以下内容的修改都必须视为安全变更：

- 身份、RBAC、内部服务 token。
- 终端票据、nonce、route、Gateway。
- sessiond、shell hook、终端录制。
- Kubernetes 资源规划、NetworkPolicy、RuntimeClass、Secret。
- Oracle、Rubric、评分和申诉。
- Agent 工具、Prompt、Provider Adapter。
- 日志、Trace、对象存储、加密和保留期。

安全变更必须完成：

1. 更新或新增负例测试。
2. 更新安全文档或 ADR。
3. 运行相关自动化测试。
4. 在状态文档记录测试命令和结果。
5. 明确仍未 live 验证的风险。
