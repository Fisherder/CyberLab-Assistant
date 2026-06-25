# CLA 题目内容开发规范

本文说明 CyberLab Assistant（CLA）中 Challenge-as-Code 题目的结构、开发流程、验证要求和安全边界。适用于教师、内容工程师和后续自动化开发 agent。

## 目标

CLA 的题目内容必须满足：

- 可版本化。
- 可验证。
- 可回放。
- 可审计。
- 可由外部 Oracle 判定客观结果。
- 可由机器 Rubric 产生可申诉成绩。
- 不泄露动态 secret、最终 payload 或教师解法。

## 目录结构

内置示例题位于：

```text
content/challenges/web-sqli-auth/
├── manifest.yaml
├── topology.yaml
├── milestones.yaml
├── rubric.yaml
├── policy/
│   ├── network.yaml
│   └── retention.yaml
├── oracle/
│   └── validator.py
├── workspace/
│   └── Dockerfile
└── target/
    ├── Dockerfile
    └── server.py
```

新增题目应保持相同结构，除非已有 JSON Schema 和内容验证逻辑支持新结构。

## Manifest

`manifest.yaml` 是题目入口，描述题目身份、版本、类别、目标、难度、workspace 类型和资源要求。

要求：

- `challenge_id` 或等价字段稳定。
- `semver` 按语义化版本递增。
- `workspace_type` 一期只能为 `TERMINAL`。
- `risk_tier` 必须与隔离策略一致。
- 题目描述不得包含动态 flag 或教师解法。
- 镜像在生产中必须使用 digest 固定。
- 修改 manifest 受控字段必须创建新 ChallengeVersion。

## Topology

`topology.yaml` 描述 workspace、target 和网络关系。

要求：

- workspace 只包含学生必要工具。
- target 只暴露题目所需端口。
- 不允许 privileged、hostPath、hostNetwork、hostPID。
- 不允许默认外连。
- 端口、环境变量和 secret 必须能被内容验证读取。

## Policy

策略文件描述网络和保留期。

网络策略要求：

- 默认拒绝 ingress 和 egress。
- 只放行 workspace 到 target 的必要端口。
- 只放行 Gateway 到 workspace sessiond。
- 不放行公网，除非题目明确需要并经过审批。

保留策略要求：

- 明确终端转录、验证报告和作业证据保留时间。
- 原始终端内容按最短必要保留。
- 删除失败需要可追踪。

## Rubric

`rubric.yaml` 是机器可读评分标准。

criterion 类型：

- `DETERMINISTIC_ORACLE`：客观通过，必须引用外部 Oracle。
- `EVENT_PATTERN`：事件模式，例如命令完成、里程碑事件或策略事件。
- `POLICY_EVENTS`：安全或策略事件。
- `LLM_RUBRIC`：开放答案评价，后续接入，不能覆盖客观 Oracle。

Rubric 要求：

- 每个 criterion 有稳定 id。
- 每个 criterion 有分值、解释、证据要求和评分器版本。
- 客观 criterion 不得仅依赖学生可控文本。
- 事件 criterion 必须引用稳定事件 type 和 source。
- 开放答案 criterion 必须定义输入字段、禁止泄露内容和人工复核条件。

## Oracle

Oracle 是客观评分边界。

要求：

- 在学生 workspace 外运行。
- 观察 target 的真实 session-specific 状态。
- 生成规范 JSON payload。
- 使用共享密钥签名。
- API 验证签名后写入 Oracle 事件。
- 正例和负例都要进入内容验证。

禁止：

- 让学生直接写通过文件。
- 读取 workspace 内学生可写文件作为唯一通过依据。
- 让 Agent 判断客观通过。
- 在 Oracle 输出中包含 secret 明文。

## Workspace 镜像

workspace 是学生终端环境。

要求：

- 默认用户为 non-root。
- 包含 `cla-sessiond` 或可运行 sessiond。
- 工作目录为 `/workspace`。
- 只安装题目需要的 CLI 工具。
- 不包含控制平面 token。
- 不包含 Docker socket、kubectl 管理权限或云凭据。
- shell hook 故障不影响 shell。

## Target 镜像

target 是被攻击或观察的服务。

要求：

- 支持 per-attempt session key。
- 不共享跨 Attempt 可变状态。
- 不把 flag 或 secret 写入普通日志。
- 不依赖公网。
- 健康检查可被内容验证调用。

## Milestones

`milestones.yaml` 描述学习里程碑，用于提示、进度和教师观察。

要求：

- 里程碑应描述行为和证据，不写完整 payload。
- 里程碑可以引用事件模式、Oracle 结果或学生提交状态。
- 里程碑触发失败不得阻塞终端。

## 内容验证流程

运行：

```bash
PYTHONPATH=services/api/src .venv/bin/python -m cla.content_validation --output content/validation/web-sqli-auth-001-1.3.0.validation.json
```

当前验证包括：

- manifest Schema。
- rubric Schema。
- target HTTP smoke。
- Oracle 正例。
- Oracle 负例。
- 报告生成。

生产内容 CI 需要继续补齐：

- 构建镜像。
- Trivy 扫描。
- SBOM。
- cosign 签名。
- 参考解。
- 资源压力测试。
- 网络策略验证。
- 负例攻击验证。

## 题库 Registry 与对象资产

当前 API 已提供本地题目导入流程：

```http
POST /api/v1/challenge-registry/import-local
GET /api/v1/challenge-registry?query=认证
```

导入行为：

- 扫描 `content/challenges/*/manifest.yaml`。
- 读取 manifest 中的 `metadata.id`、`metadata.version`、`metadata.title` 和 `spec.category`。
- 对每个题目包执行内容验证。
- 将题目包打成确定性 tar 对象。
- 将对象写入 `CLA_CHALLENGE_ARTIFACT_STORAGE_BACKEND` 指定的后端。
- 在 `challenge_artifacts` 表记录 `object_ref`、`sha256`、字节数和资产元数据。
- 已存在的 `ChallengeVersion` 不会被静默覆盖；新版本进入 `PENDING_APPROVAL`。

本地对象存储配置：

```bash
CLA_CHALLENGE_ARTIFACT_STORAGE_BACKEND=local
CLA_CHALLENGE_ARTIFACT_OBJECT_ROOT=/tmp/cla-challenge-artifacts
```

MinIO/S3 配置：

```bash
CLA_CHALLENGE_ARTIFACT_STORAGE_BACKEND=s3
CLA_CHALLENGE_ARTIFACT_S3_BUCKET=cla-challenge-artifacts
CLA_CHALLENGE_ARTIFACT_S3_PREFIX=challenge-artifacts
CLA_CHALLENGE_ARTIFACT_S3_ENDPOINT_URL=http://localhost:9000
CLA_CHALLENGE_ARTIFACT_S3_REGION=us-east-1
CLA_CHALLENGE_ARTIFACT_S3_FORCE_PATH_STYLE=true
```

对象引用只能由服务端生成和消费。前端可以看到摘要和引用计数，但不得获得任何运行时 secret、容器内部地址或控制面凭据。

## 检索规则

当前 Registry 检索由两层组成：

1. 硬约束过滤：tenant、版本状态、类别、工作区类型、隔离等级、难度、预计时长、外连策略和允许工具。
2. BM25 风格全文得分：题目 slug、标题、类别、学习目标、前置知识和 workspace 工具。

响应中包含：

- `score`：综合候选分。
- `searchScore`：归一化全文得分。
- `retrievalSignals.metadata`：元数据匹配信号。
- `retrievalSignals.bm25`：全文检索信号。
- `retrievalSignals.vector`：当前为 `0`，保留给后续 pgvector/OpenSearch。

向量检索尚未启用。启用前必须保证动态 secret、最终 payload、教师解法和学生私有轨迹不会进入向量索引。

## 版本规则

题目版本是不可变发布单元。

必须创建新版本的情况：

- 修改 manifest、topology、policy、rubric、Oracle、target 行为、workspace 工具或动态 secret 生成方式。
- 修改评分分值、criterion id 或证据要求。
- 修改影响 Attempt 可重放性的内容。
- 修改镜像 digest。

可以不创建新版本的情况：

- 修正文档错别字，且不影响题目行为。
- 添加内部注释，且不影响构建和验证。
- 更新未发布草稿。

## 教师 Brief 到题目发布

当前链路：

1. 教师提交 Brief。
2. API 优先调用配置的模型解析 CourseIntent；模型关闭、缺配置或返回不合格 JSON 时回退规则解析。
3. 候选题执行硬过滤和 BM25 风格检索。
4. 教师选择候选。
5. 模型可生成版本草稿、Rubric 草稿和教师审核清单。
6. API 创建 `PENDING_APPROVAL` ChallengeVersion，并记录模型输出、对象资产和验证报告。
7. 教师打开验证报告并审批。
8. 作业引用不可变 ChallengeVersion。

模型接入配置写入 `.env`：

```bash
CLA_AGENT_RUNTIME_ENABLED=true
CLA_MODEL_PROVIDER=openai-compatible
CLA_MODEL_BASE_URL=https://api.deepseek.com
CLA_MODEL_NAME=deepseek-v4-flash
CLA_MODEL_API_KEY=你的模型密钥
```

Agent 边界：

- Agent 只能做 Brief 解析和版本草稿。
- Agent 不能直接部署 target。
- Agent 不能直接发布版本。
- Agent 不能获得 Shell、SQL、Docker、Kubernetes 或任意 HTTP 工具。
- 低置信字段必须显式展示给教师。
- 教师审批事件必须写审计。
- `AgentRun` 记录用途、模型策略、输出、状态和用量，不记录 API Key。

## 题目安全审查清单

发布前必须确认：

- 一期 workspace type 是 `TERMINAL`。
- 没有 GUI/RDP/VNC/桌面运行依赖。
- 没有 privileged、hostPath、hostNetwork、hostPID。
- 没有自动挂载 ServiceAccount token。
- 网络默认拒绝。
- secret 不在 manifest、rubric、日志和验证报告中明文出现。
- Oracle 在外部边界运行并验签。
- Rubric 每项有证据引用。
- 负例不能通过。
- shell hook 关闭时终端仍可用。
- Agent Runtime 关闭时客观评分仍可用。

## 题目文档规范

题目文档面向中文教师和开发人员：

- 说明学习目标。
- 说明预期时长和难度。
- 说明允许工具。
- 说明隔离等级和网络限制。
- 说明评分标准和证据来源。
- 说明已知限制和教师复核建议。
- 不写完整攻击 payload、动态 secret 或教师解法。

## 常见反模式

禁止以下做法：

- 在 target 中写 `/tmp/success`，然后把它作为唯一通过证据。
- 在前端暴露 target 内部地址、sessiond 地址或 route。
- 把题目 flag 固定写在 Dockerfile。
- 让 shell hook 事件直接给满分。
- 让 Agent 根据终端输出直接判定客观通过。
- 发布没有负例 Oracle 的题目。
- 修改已发布版本而不创建新版本。
- 把真实学生终端明文放进验证报告或普通日志。
