# CyberLab Assistant（CLA）教师端使用手册

题目维护、验证发布、作业监控、成绩证据与申诉复核

- 适用对象：教师、助教、内容工程师、课程专家
- 生成日期：2026-06-25
- 项目名称：CyberLab Assistant（CLA）
- 相关规格：`cla_terminal_first_complete_development_spec.html`

## 目录

1. [文档定位与阅读方式](#文档定位与阅读方式)
2. [教师角色、权限与安全边界](#教师角色权限与安全边界)
3. [课前准备与本地实例检查](#课前准备与本地实例检查)
4. [登录与开发 token 使用](#登录与开发-token-使用)
5. [教师端页面入口总览](#教师端页面入口总览)
6. [课程创建与成员维护](#课程创建与成员维护)
7. [Challenge-as-Code 题目包概念](#challenge-as-code-题目包概念)
8. [从教学 Brief 创建题目草稿](#从教学-brief-创建题目草稿)
9. [候选题检索与选择](#候选题检索与选择)
10. [Materialize 题目版本并生成验证报告](#materialize-题目版本并生成验证报告)
11. [题目验证报告页使用方法](#题目验证报告页使用方法)
12. [审批发布 ChallengeVersion](#审批发布-challengeversion)
13. [创建作业与发布给学生](#创建作业与发布给学生)
14. [作业实时监控页使用方法](#作业实时监控页使用方法)
15. [查看学生成绩证据](#查看学生成绩证据)
16. [申诉复核与教师覆盖成绩](#申诉复核与教师覆盖成绩)
17. [课堂辅助信号的解释方式](#课堂辅助信号的解释方式)
18. [题目发布前安全检查清单](#题目发布前安全检查清单)
19. [教师端常见问题与处理](#教师端常见问题与处理)
20. [教师端 API 速查](#教师端-api-速查)

<a id="文档定位与阅读方式"></a>
## 1. 文档定位与阅读方式

本文是 CyberLab Assistant（CLA）教师端使用手册，面向课程教师、助教、内容工程师和需要审核题目质量的专家。它覆盖当前本地实例已经提供的教师功能，也说明仍需通过 API 操作或仍处于一期后续建设中的边界。

> **当前实现边界**：教师端的直接页面目前包括题目验证报告页和作业实时监控页。课程管理、成员管理、题目草稿、作业创建、申诉复核等能力已经有 API，但还没有完整教师图形界面。

| 用途 | 入口或接口 | 当前状态 |
| --- | --- | --- |
| 题目验证报告 | `/teacher/challenges/{versionId}/validation` | 页面可直接操作，可刷新、查看检查项、审批发布 |
| 作业实时监控 | `/teacher/assignments/{assignmentId}/live` | 页面可直接操作，可查看会话状态、辅助状态和告警计数 |
| 课程与成员 | `POST /api/v1/courses`、`PUT /api/v1/courses/{courseId}/members/{userId}` | API 可用，当前无独立页面 |
| 题目草稿与候选 | `POST /api/v1/challenge-drafts`、候选与 materialize 接口 | API 可用，当前无独立页面 |
| 作业创建 | `POST /api/v1/assignments` | API 可用，当前无独立页面 |
| 成绩查看 | `GET /api/v1/attempts/{attemptId}/grade` | 教师可通过 API 查看课程内学生成绩 |
| 申诉复核 | `POST /api/v1/appeals/{appealId}/resolve` | API 可用，当前无独立页面 |

- 本手册只使用 CLA/CyberLab Assistant 项目名，不再使用历史旧缩写。
- 所有示例均以本地开发实例为准：Web 默认 `http://127.0.0.1:3000`，API 默认 `http://127.0.0.1:8000`。
- 生产环境 URL、OIDC 登录方式和开发 token 策略由管理员替换，本手册中的接口路径和页面路径保持一致。
- 遇到运行环境差异时，优先查阅 `docs/runbooks/local-development.md` 和 `docs/implementation/status.md`。


<a id="教师角色权限与安全边界"></a>
## 2. 教师角色、权限与安全边界

教师角色用于管理课程、维护题目、创建作业、查看班级状态、审核发布和复核申诉。助教角色在当前实现中可执行大多数课程内教师操作，但具体生产策略可由管理员收紧。

| 操作 | 需要角色 | 安全说明 |
| --- | --- | --- |
| 创建课程 | 平台教师或拥有开发 token 的教师 | 课程归属当前租户，跨租户访问被拒绝 |
| 维护课程成员 | 课程教师或助教 | 只能给课程内用户设置 `STUDENT`、`TEACHER`、`TA` |
| 创建题目草稿 | 课程教师或助教 | Brief 被视为不可信输入，不能覆盖系统指令 |
| 审批题目版本 | 课程教师或助教 | 有 BLOCK 检查项时不能发布 |
| 创建作业 | 课程教师或助教 | 只能引用已发布的 ChallengeVersion |
| 查看 live monitor | 课程教师或助教 | 默认不展示学生终端明文 |
| 查看成绩 | 课程教师或助教 | 只能查看本课程 Attempt 的 GradeRevision |
| 复核申诉 | 课程教师或助教 | 复核会生成审计记录，覆盖成绩会生成新 Revision |

> **不可突破的边界**：教师端不能获得学生容器地址、Pod 名称、sessiond 地址、Kubernetes 凭据、动态 flag、内部 token 或模型密钥。验证报告、监控和成绩页只展示经过平台约束后的状态、证据引用和统计信息。

- 不要把题目最终 payload、动态 secret 或教师解法写入 Brief、题目描述、Rubric 解释或公开附件。
- 不要根据终端文本直接判定客观通过；客观得分必须来自外部 Oracle 或平台签名事件。
- 不要把 live monitor 的辅助状态等同于作弊结论；它只是教学干预信号。
- 不要要求学生提交平台 token、浏览器 localStorage 内容或终端票据。


<a id="课前准备与本地实例检查"></a>
## 3. 课前准备与本地实例检查

上课或演示前，教师应确认控制平面、终端网关、sessiond 和 Web 已启动，并且开发 token 或生产登录方式可用。本地实例的详细启动方式见本仓库运行手册。

1. 确认 API 健康检查返回 `{"ok":true,"agentRuntimeEnabled":false}` 或生产环境的等价健康状态。
2. 确认 Gateway 健康检查返回 `ok`，并且 API 与 Gateway 使用一致的内部服务 token。
3. 确认 Web 页面可打开，静态资源没有 chunk 404 或 ChunkLoadError。
4. 确认教师 token 已写入浏览器 `localStorage.claDevToken`，生产环境则确认 OIDC 登录后具备教师角色。
5. 打开默认题目验证报告页，确认 `Overall` 不是 `BLOCK`。
6. 打开默认作业 live monitor，确认页面能加载作业标题和统计卡片。
7. 抽测一个学生账户创建 Attempt、连接终端、提交答案、生成成绩与申诉。

```bash
curl --noproxy '*' -sS http://127.0.0.1:8000/healthz
curl --noproxy '*' -sS http://127.0.0.1:8081/healthz
curl --noproxy '*' -I http://127.0.0.1:3000/
```

> **环境限制**：当前本机记录显示 Docker daemon 与 Kubernetes 集群不可用时，不能把 Compose live smoke、真实 K8s NetworkPolicy、gVisor/Kata 或节点故障测试标记为已验证。教师演示可以使用当前本地终端切片，但正式靶场部署仍需要可用容器运行环境。


<a id="登录与开发-token-使用"></a>
## 4. 登录与开发 token 使用

生产环境应通过学校或平台 OIDC 登录。当前本地开发实例支持 `CLA_DEV_MODE=true` 下的开发 token，用于教师和学生角色测试。

1. 在项目根目录生成开发 token。
2. 复制教师 token。
3. 打开浏览器控制台，把 token 写入 `localStorage.claDevToken`。
4. 刷新教师页面，API 请求会自动携带 `Authorization: Bearer <token>`。
5. 切换学生视角测试时，覆盖为学生 token。

```bash
PYTHONPATH=services/api/src .venv/bin/python -m cla.dev_tokens

// 在浏览器控制台写入教师 token
localStorage.setItem("claDevToken", "<teacher-token>")

// 清理 token
localStorage.removeItem("claDevToken")
```

| 现象 | 可能原因 | 处理方式 |
| --- | --- | --- |
| 页面显示认证失败或 API 返回 401 | 未设置 token、token 过期、开发模式未开启 | 重新生成 token，确认 `CLA_DEV_MODE=true` |
| 教师页面返回 403 | 当前 token 不是课程教师或助教 | 检查课程成员或改用教师 token |
| 学生能打开教师页面但接口失败 | 页面可路由不代表有权限 | 以接口返回为准，确认角色 |


<a id="教师端页面入口总览"></a>
## 5. 教师端页面入口总览

当前 Web 首屏是学生工作台，但教师可直接访问教师路由。默认种子数据提供一个 Web SQL 登录题和一个作业，适合用作演示与验收。

| 页面 | 默认示例地址 | 用途 |
| --- | --- | --- |
| 题目验证报告 | `http://127.0.0.1:3000/teacher/challenges/cv_web_sqli_auth_1_3_0/validation` | 查看 ChallengeVersion 的验证结果、风险、证据引用并审批发布 |
| 作业实时监控 | `http://127.0.0.1:3000/teacher/assignments/asg_web_sqli_auth/live` | 查看班级 Attempt、LabSession、卡住状态、提示状态和告警计数 |
| 学生工作台 | `http://127.0.0.1:3000/` | 教师可用学生 token 进行演示路径验证 |
| 学生成绩证据页 | `http://127.0.0.1:3000/student/grades/{attemptId}` | 学生查看成绩；教师通过 API 可查看同一 Attempt 的成绩数据 |

> **IPv6 访问说明**：如果使用 IPv6 地址访问本机 Web，页面会把 API 返回的本地回环 Gateway WebSocket 地址改写为当前页面主机，避免浏览器尝试连接访问者自己的 `127.0.0.1`。


<a id="课程创建与成员维护"></a>
## 6. 课程创建与成员维护

课程是作业、题目草稿、成员权限和监控范围的上层归属。当前课程与成员维护通过 API 完成。所有写接口应带 `Idempotency-Key` 或遵循接口自身幂等设计，避免刷新或重试创建重复数据。

```bash
export CLA_API=http://127.0.0.1:8000
export CLA_TEACHER_TOKEN=<teacher-token>

curl -sS -X POST "$CLA_API/api/v1/courses" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "WEBSEC-101",
    "title": "Web 安全实践",
    "term": "2026 春"
  }'

curl -sS -X PUT "$CLA_API/api/v1/courses/<course-id>/members/<student-user-id>" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role":"STUDENT"}'
```

| 字段 | 含义 | 建议 |
| --- | --- | --- |
| `code` | 课程代码 | 使用学校或课程组统一编码 |
| `title` | 课程名称 | 面向学生可读，不写内部管理信息 |
| `term` | 学期或开课周期 | 用于归档和过滤 |
| 成员 `role` | `STUDENT`、`TEACHER`、`TA` | 按最小权限分配，助教离课后及时移除 |


<a id="challenge-as-code-题目包概念"></a>
## 7. Challenge-as-Code 题目包概念

CLA 的题目采用 Challenge-as-Code。一个题目版本应能被验证、签名、回放和审计。教师不应把题目当作一段普通说明文字，而应把它看作包含目标服务、workspace、策略、Oracle、Rubric 和里程碑的可验证包。

```bash
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

- `manifest.yaml` 描述题目身份、版本、类别、难度、workspace 类型和资源要求。
- `topology.yaml` 描述 workspace、target 与网络关系。
- `policy/` 描述网络默认拒绝、保留期和安全限制。
- `oracle/` 在学生控制边界外判定客观通过，输出带签名的证据事件。
- `rubric.yaml` 定义每个评分项的分值、证据、评分器类型和版本。
- `milestones.yaml` 用于教学提示和进度判断，但不能泄露最终 payload。

> **一期范围**：一期只支持 `WorkspaceType=TERMINAL`。`REMOTE_DESKTOP` 和 `SIMULATED` 只是类型和 Feature Flag 预留，不应在题目包里引入 RDP/VNC、桌面环境、Guacamole、视觉观察或文档模拟依赖。


<a id="从教学-brief-创建题目草稿"></a>
## 8. 从教学 Brief 创建题目草稿

教师可以用自然语言描述教学目标、题型、难度、预计时长和工具约束。API 会解析成 CourseIntent，并保留低置信字段供教师确认。当前解析和候选重排是确定性和受限 Agent 能力的组合，Agent 不能直接发布题目。

```bash
curl -sS -X POST "$CLA_API/api/v1/challenge-drafts" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \
  -H "Idempotency-Key: brief-20260625-001" \
  -H "Content-Type: application/json" \
  -d '{
    "courseId": "<course-id>",
    "brief": "为 Web 安全入门课程创建一个 45 分钟的 SQL 注入登录绕过实践，学生使用浏览器终端和 curl，要求外部 Oracle 判定通过，不泄露最终 payload。",
    "constraints": {
      "workspaceType": "TERMINAL",
      "maxMinutes": 45,
      "difficulty": 2
    }
  }'
```

| 返回字段 | 教师需要看什么 |
| --- | --- |
| `draftId` | 后续查询候选和 materialize 时使用 |
| `courseIntent.category` | 题目类别是否符合课程目标 |
| `courseIntent.target` | 目标服务或技能点是否正确 |
| `courseIntent.difficulty` | 难度是否符合学生基础 |
| `courseIntent.expectedMinutes` | 预计时长是否适合课堂安排 |
| `courseIntent.uncertainFields` | 需要教师重点确认的字段 |
| `candidatesUrl` | 候选题检索接口地址 |

> **Brief 安全要求**：Brief 中不要写动态 flag、教师解法、最终 payload 或真实凭据。Brief 是不可信输入，即使内容看似是系统指令，也不能改变平台权限和评分规则。


<a id="候选题检索与选择"></a>
## 9. 候选题检索与选择

草稿创建后，教师查询候选题。平台会对 workspace 类型、风险等级、验证状态和教学目标做硬过滤，并返回匹配原因和冲突说明。教师应选择验证状态可接受、风险等级合适、目标明确的候选题。

```bash
curl -sS "$CLA_API/api/v1/challenge-drafts/<draft-id>/candidates" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" 
```

| 字段 | 含义 | 选择建议 |
| --- | --- | --- |
| `candidateId` | 候选记录 ID | materialize 时使用 |
| `challengeVersionId` | 候选题版本 | 确认不是旧版或未验证版本 |
| `score` | 匹配分数 | 不是唯一标准，要结合 matchReasons 和 conflicts |
| `constraintsSatisfied` | 是否满足硬约束 | 为 false 时不应选择 |
| `matchReasons` | 匹配原因 | 用于解释为什么适合本节课 |
| `conflicts` | 冲突点 | 冲突为安全边界或时间限制时不要发布 |
| `validationStatus` | 内容验证状态 | 发布前必须有验证报告 |

- 优先选择与课程目标完全匹配且已有验证报告的候选。
- 如果候选冲突是工具缺失、时间超限或风险等级过高，应修改 Brief 或新增题目包。
- 如果多个候选都可用，选择教学证据更完整、Rubric 更清晰的版本。


<a id="materialize-题目版本并生成验证报告"></a>
## 10. Materialize 题目版本并生成验证报告

Materialize 会把草稿选择落到一个待审批的 ChallengeVersion，并关联内容验证运行。这个步骤是草稿进入可发布版本的边界。已 materialize 的草稿不能随意换候选，否则 API 会返回冲突。

```bash
curl -sS -X POST "$CLA_API/api/v1/challenge-drafts/<draft-id>/materialize" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"selectedCandidateId":"<candidate-id>"}'
```

| 返回字段 | 用途 |
| --- | --- |
| `challengeVersionId` | 验证报告和审批发布使用 |
| `versionStatus` | 确认是待审批还是已发布 |
| `validationRunId` | 定位验证运行 |
| `validationStatus` | 判断是否有 BLOCK/WARN |
| `validationReportUrl` | 教师打开验证报告的 API 路径 |
| `approvalRequired` | 是否还需要教师审批 |


<a id="题目验证报告页使用方法"></a>
## 11. 题目验证报告页使用方法

验证报告页是教师发布题目前最重要的页面。它展示 ChallengeVersion 的总体状态、检查摘要、验证元数据、分组检查项、证据引用和已检查的禁止泄露类别。

1. 打开 `/teacher/challenges/{versionId}/validation`。
2. 查看顶部 `Overall`，只有 `PASS` 或可接受的 `WARN` 才能继续审批；`BLOCK` 必须先修复题目。
3. 查看 `Pass`、`Warn`、`Block` 计数，确认 Block 为 0。
4. 查看 `Artifact`，确认题目包 digest 与待发布版本一致。
5. 查看 `Workflow`、`Started`、`Ended`，确认验证不是旧报告。
6. 逐组展开检查项，关注 `SCHEMA`、`BUILD`、`SCAN`、`RUNTIME`、`SOLVE`、`ORACLE`、`RESOURCE`、`TUTOR`、`WORKSPACE` 等类别。
7. 查看每个检查项的 evidence refs。证据引用缺失或含义不清时，不应发布。
8. 检查 Forbidden disclosure classes，确认动态 secret、最终 payload、教师解法、token 等类别都已纳入扫描。
9. 点击 `刷新` 获取最新报告。

| 状态 | 含义 | 教师处理 |
| --- | --- | --- |
| `PASS` | 检查通过 | 可进入审批判断 |
| `WARN` | 发现警告但不阻断 | 阅读证据，确认是否可在课堂中接受 |
| `BLOCK` | 阻断发布 | 必须修复题目包或策略后重新验证 |

> **报告内容边界**：验证报告不是教师解法页。报告中不应出现最终 payload、动态 secret、真实学生终端明文或控制平面凭据。如果看到这类内容，应停止发布并修复内容验证规则。


<a id="审批发布-challengeversion"></a>
## 12. 审批发布 ChallengeVersion

题目版本只有审批发布后才能被作业引用。页面右上角的 `审批发布` 按钮会调用发布接口。版本已发布后按钮显示 `已发布`，再次点击不会重复发布。

1. 确认验证报告 `Block` 为 0。
2. 确认所有 `WARN` 已阅读，且不影响安全、评分或课堂可用性。
3. 确认题目没有 GUI/RDP/VNC 依赖，workspace type 是 `TERMINAL`。
4. 确认 Oracle 正例和负例都通过验证，不能被学生伪造。
5. 确认 Rubric 每个 criterion 有稳定证据引用。
6. 点击 `审批发布`。
7. 看到 `审批已发布` 或 `版本已发布` 后刷新页面。

```bash
curl -sS -X POST "$CLA_API/api/v1/challenge-versions/<version-id>/approve" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" 
```

> **版本不可变**：发布后的 ChallengeVersion 应视为不可变。修改 manifest、topology、policy、rubric、Oracle、target 行为、workspace 工具或镜像 digest 都应创建新版本。


<a id="创建作业与发布给学生"></a>
## 13. 创建作业与发布给学生

作业把课程、已发布 ChallengeVersion、开放时间、截止时间和尝试策略绑定在一起。当前作业创建通过 API 完成。学生工作台默认使用环境变量中的 `NEXT_PUBLIC_CLA_ASSIGNMENT_ID`，本地默认是 `asg_web_sqli_auth`。

```bash
curl -sS -X POST "$CLA_API/api/v1/assignments" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \
  -H "Idempotency-Key: assignment-20260625-001" \
  -H "Content-Type: application/json" \
  -d '{
    "courseId": "<course-id>",
    "challengeVersionId": "<published-version-id>",
    "title": "SQL 注入登录绕过实践",
    "openAt": "2026-06-25T09:00:00Z",
    "dueAt": "2026-06-25T11:00:00Z",
    "attemptPolicy": {
      "maxAttempts": 1,
      "maxResets": 2
    }
  }'
```

| 字段 | 说明 | 注意事项 |
| --- | --- | --- |
| `courseId` | 所属课程 | 教师必须是该课程教师或助教 |
| `challengeVersionId` | 题目版本 | 必须是已发布版本 |
| `title` | 学生看到的作业名 | 不写最终解法或 secret |
| `openAt` | 开放时间 | 为空时默认当前时间 |
| `dueAt` | 截止时间 | 为空表示未设置截止 |
| `attemptPolicy.maxAttempts` | 尝试次数 | 本地默认 1 |
| `attemptPolicy.maxResets` | 重置次数 | 用于限制环境重置频率 |


<a id="作业实时监控页使用方法"></a>
## 14. 作业实时监控页使用方法

作业实时监控页用于课堂中观察整体状态，而不是观看学生终端明文。它帮助教师发现环境未就绪、疑似卡住、资源或安全告警等情况，并决定是否进行课堂干预。

1. 打开 `/teacher/assignments/{assignmentId}/live`。
2. 查看页面标题确认进入正确作业。
3. 查看 `更新` 时间，必要时点击 `刷新`。
4. 查看顶部统计卡：Attempts、Ready、Stuck、Resource、Security。
5. 在会话表中查看每个学生的 Attempt ID、session 状态、epoch、辅助状态、最近提示和最近事件时间。
6. 优先处理 Resource 或 Security 告警数量较高的学生。
7. 对 `CONFIRMED` 或高分疑似卡住学生，可先线下询问，不要直接给最终 payload。

| 字段 | 含义 | 教师动作 |
| --- | --- | --- |
| `Attempts` | 作业下 Attempt 总数 | 确认学生是否都已开始 |
| `Ready` | 已就绪 LabSession 数 | 低于预期时检查环境 |
| `Stuck` | 疑似卡住数量 | 用于安排提醒或巡查 |
| `Resource` | 资源类告警 | 检查容器、配额或长输出 |
| `Security` | 安全类告警 | 检查策略事件，但不能直接判作弊 |
| `sessionStatus` | 单个会话状态 | `READY` 表示终端环境可用 |
| `latestHint` | 最近提示等级与状态 | 判断学生是否已收到辅助 |

> **隐私与证据边界**：live monitor 默认不展示完整终端明文。终端文本属于学生可控弱证据，系统只在证据页和审计链中引用经过策略处理的事件和片段引用。


<a id="查看学生成绩证据"></a>
## 15. 查看学生成绩证据

学生提交后，系统会创建不可变 GradeRevision。教师可通过 API 查看课程内 Attempt 的最新成绩。成绩由总分、独立完成指数、Rubric 版本、Grader 版本和 CriterionResult 组成。

```bash
curl -sS "$CLA_API/api/v1/attempts/<attempt-id>/grade" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" 
```

| 字段 | 含义 | 教学用途 |
| --- | --- | --- |
| `totalScore` | 总分 | 对学生正式成绩的核心显示值 |
| `independenceIndex` | 独立完成指数 | 提示使用和辅助依赖的说明指标，不改变总分 |
| `revisionNo` | 成绩修订号 | 申诉覆盖后递增 |
| `rubricVersion` | 评分标准版本 | 追溯本次评分依据 |
| `graderVersion` | 评分器版本 | 追溯自动评分实现 |
| `criteria[].criterionId` | 评分项 ID | 申诉和覆盖时按项处理 |
| `criteria[].score/maxScore` | 单项得分 | 定位失分点 |
| `criteria[].graderType` | 评分类型 | 区分 Oracle、事件模式和开放评价 |
| `criteria[].confidence` | 置信度 | 低置信应人工复核 |
| `criteria[].evidenceRefs` | 证据引用 | 判断分数是否可追溯 |

> **复核材料边界**：教师复核时应围绕 evidence refs 和 Rubric 解释讨论，不应要求学生提供动态 token、终端票据或系统内部路由。


<a id="申诉复核与教师覆盖成绩"></a>
## 16. 申诉复核与教师覆盖成绩

学生在成绩证据页按 criterion 提交申诉后，教师可复核。复核结果可以维持原成绩，也可以覆盖指定 criterion 分数。覆盖不会修改旧 GradeRevision，而是生成新的 GradeRevision，保留原始记录和审计链。

```bash
# 维持原成绩
curl -sS -X POST "$CLA_API/api/v1/appeals/<appeal-id>/resolve" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "UPHOLD_ORIGINAL",
    "resolution": "Oracle 证据和 Rubric 解释一致，维持原评分。",
    "criterionOverrides": []
  }'

# 覆盖某个评分项
curl -sS -X POST "$CLA_API/api/v1/appeals/<appeal-id>/resolve" \
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "OVERRIDE_SCORE",
    "resolution": "学生补充解释表明根因分析满足评分项要求，调整该项得分。",
    "criterionOverrides": [
      {
        "criterionId": "root-cause",
        "score": 30,
        "explanation": "教师复核覆盖：根因说明完整，证据与提交内容一致。"
      }
    ]
  }'
```

- 只能复核状态为 `OPEN` 的 Appeal。
- `OVERRIDE_SCORE` 必须覆盖学生申诉的那个 criterion，否则 API 会拒绝。
- 覆盖分数不能超过该 criterion 的 `maxScore`。
- 复核说明 `resolution` 应写清事实依据、引用证据和最终决定。
- 如果需要调整多个相关 criterion，应确保每个 criterion 都存在于原 GradeRevision 中。


<a id="课堂辅助信号的解释方式"></a>
## 17. 课堂辅助信号的解释方式

CLA 的 Tutor 侧重教学辅助。系统会根据重复命令、相同错误、里程碑停滞、探索新颖度、长任务排除等特征判断学生是否可能卡住，并提供 L1 到 L3 分级提示。

| 状态或字段 | 含义 | 教师解释 |
| --- | --- | --- |
| `NORMAL` | 未发现明显卡住 | 无需干预，继续观察 |
| `SUSPECTED` | 疑似卡住 | 可提醒学生查看题目目标或请求 L1 提示 |
| `CONFIRMED` | 卡住概率高 | 可进行非答案式引导 |
| `score` | 卡住评分 | 不是成绩分，也不是作弊概率 |
| `latestHint.level` | 最近提示等级 | L1 最轻，L3 更具体 |
| `AUTO_DISABLED` | 学生关闭自动提示 | 尊重学生选择，不因此扣分 |

> **独立完成指数**：提示使用只影响独立完成指数，不直接改变总分。教师应把该指数作为学习过程参考，而不是单独惩罚依据。


<a id="题目发布前安全检查清单"></a>
## 18. 题目发布前安全检查清单

- [ ] 题目版本 workspace type 为 `TERMINAL`。
- [ ] 题目包没有 GUI、RDP、VNC、Guacamole、桌面环境或视觉模型依赖。
- [ ] 没有 privileged、hostPath、hostNetwork、hostPID 或自动挂载 ServiceAccount token。
- [ ] 网络策略默认拒绝，只放行 workspace 到 target 的必要端口以及 Gateway 到 sessiond 的路径。
- [ ] manifest、rubric、日志、验证报告和公开附件中没有动态 secret、最终 payload 或教师解法。
- [ ] Oracle 在学生 workspace 外运行，并且正例和负例都通过验证。
- [ ] Rubric 每个 criterion 有分值、解释、证据引用和评分器版本。
- [ ] Shell hook、Tutor 或 Agent 不可用时，学生仍可使用终端和客观评分。
- [ ] 发布前验证报告没有 BLOCK，所有 WARN 都已人工确认。
- [ ] 状态文档记录了本次实际运行命令、测试结果和已知限制。


<a id="教师端常见问题与处理"></a>
## 19. 教师端常见问题与处理

| 问题 | 可能原因 | 处理步骤 |
| --- | --- | --- |
| 验证报告页面加载失败 | token 缺失、无课程权限、versionId 错误或 API 未启动 | 检查 localStorage、API healthz 和版本 ID |
| 审批按钮不可用 | 报告为 BLOCK、版本已发布或验证报告不存在 | 先修复题目并重新验证，已发布版本无需再次审批 |
| 作业创建返回 `CHALLENGE_VERSION_NOT_PUBLISHED` | 引用了未发布版本 | 先进入验证报告页审批发布 |
| live monitor 没有会话 | 学生尚未创建 Attempt 或 assignmentId 错误 | 让学生点击启动，确认作业 ID |
| 学生终端票据被拒 | 票据超过 60 秒、nonce 重放、Gateway 与 API token 不一致 | 让学生重新点击启动或重连，检查 Gateway 配置 |
| 成绩不存在 | 学生未提交、评分流程未完成或 attemptId 错误 | 确认学生已点击提交并刷新成绩 |
| 申诉复核失败 | Appeal 非 OPEN、覆盖项不是被申诉项、分数超过 maxScore | 按接口错误码修正请求 |
| Docker/Compose live smoke 不能运行 | 本机 Docker daemon 不可用 | 只能标记静态配置验证，不能标记 live 验证完成 |


<a id="教师端-api-速查"></a>
## 20. 教师端 API 速查

| 功能 | 方法与路径 | 说明 |
| --- | --- | --- |
| 当前用户 | `GET /api/v1/me` | 查看登录身份和角色上下文 |
| 创建课程 | `POST /api/v1/courses` | 创建课程 |
| 维护成员 | `PUT /api/v1/courses/{courseId}/members/{userId}` | 设置课程角色 |
| 创建题目草稿 | `POST /api/v1/challenge-drafts` | 从 Brief 生成 CourseIntent |
| 查看候选 | `GET /api/v1/challenge-drafts/{draftId}/candidates` | 检索候选题 |
| 生成版本 | `POST /api/v1/challenge-drafts/{draftId}/materialize` | 选择候选并生成待审批版本 |
| 查看验证 | `GET /api/v1/challenge-versions/{versionId}/validation` | 读取验证报告 |
| 审批发布 | `POST /api/v1/challenge-versions/{versionId}/approve` | 发布题目版本 |
| 创建作业 | `POST /api/v1/assignments` | 引用已发布版本创建作业 |
| 实时监控 | `GET /api/v1/assignments/{assignmentId}/live` | 教师 live monitor 数据 |
| 查看成绩 | `GET /api/v1/attempts/{attemptId}/grade` | 查看最新 GradeRevision |
| 复核申诉 | `POST /api/v1/appeals/{appealId}/resolve` | 维持或覆盖成绩 |

> **内部接口**：内部接口 `/internal/...` 仅供 Gateway、sessiond、Oracle、环境控制器等可信服务调用，教师日常使用不应直接调用。
