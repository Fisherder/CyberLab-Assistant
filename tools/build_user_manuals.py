from __future__ import annotations

import html
import re
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = ROOT / "docs" / "user-manuals"
PDF_DIR = ROOT / "output" / "pdf"
GENERATED_AT = datetime.now().strftime("%Y-%m-%d")
PDF_FONT_NAME = "CLAChinese"
PDF_FONT_FALLBACK = "STSong-Light"
ACTIVE_PDF_FONT_NAME = PDF_FONT_NAME
PDF_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
]


@dataclass(frozen=True)
class Manual:
    slug: str
    title: str
    subtitle: str
    audience: str
    pdf_name: str
    sections: list[dict[str, Any]]


def block(kind: str, content: Any = None, **kwargs: Any) -> dict[str, Any]:
    data = {"kind": kind, "content": content}
    data.update(kwargs)
    return data


def teacher_manual() -> Manual:
    sections = [
        {
            "title": "文档定位与阅读方式",
            "blocks": [
                block(
                    "p",
                    "本文是 CyberLab Assistant（CLA）教师端使用手册，面向课程教师、助教、内容工程师和需要审核题目质量的专家。它覆盖当前本地实例已经提供的教师功能，也说明仍需通过 API 操作或仍处于一期后续建设中的边界。",
                ),
                block(
                    "note",
                    "教师端的直接页面目前包括题目验证报告页和作业实时监控页。课程管理、成员管理、题目草稿、作业创建、申诉复核等能力已经有 API，但还没有完整教师图形界面。",
                    title="当前实现边界",
                ),
                block(
                    "table",
                    headers=["用途", "入口或接口", "当前状态"],
                    rows=[
                        ["题目验证报告", "`/teacher/challenges/{versionId}/validation`", "页面可直接操作，可刷新、查看检查项、审批发布"],
                        ["作业实时监控", "`/teacher/assignments/{assignmentId}/live`", "页面可直接操作，可查看会话状态、辅助状态和告警计数"],
                        ["课程与成员", "`POST /api/v1/courses`、`PUT /api/v1/courses/{courseId}/members/{userId}`", "API 可用，当前无独立页面"],
                        ["题目草稿与候选", "`POST /api/v1/challenge-drafts`、候选与 materialize 接口", "API 可用，当前无独立页面"],
                        ["作业创建", "`POST /api/v1/assignments`", "API 可用，当前无独立页面"],
                        ["成绩查看", "`GET /api/v1/attempts/{attemptId}/grade`", "教师可通过 API 查看课程内学生成绩"],
                        ["申诉复核", "`POST /api/v1/appeals/{appealId}/resolve`", "API 可用，当前无独立页面"],
                    ],
                ),
                block(
                    "bullets",
                    [
                        "本手册只使用 CLA/CyberLab Assistant 项目名，不再使用历史旧缩写。",
                        "所有示例均以本地开发实例为准：Web 默认 `http://127.0.0.1:3000`，API 默认 `http://127.0.0.1:8000`。",
                        "生产环境 URL、OIDC 登录方式和开发 token 策略由管理员替换，本手册中的接口路径和页面路径保持一致。",
                        "遇到运行环境差异时，优先查阅 `docs/runbooks/local-development.md` 和 `docs/implementation/status.md`。",
                    ],
                ),
            ],
        },
        {
            "title": "教师角色、权限与安全边界",
            "blocks": [
                block(
                    "p",
                    "教师角色用于管理课程、维护题目、创建作业、查看班级状态、审核发布和复核申诉。助教角色在当前实现中可执行大多数课程内教师操作，但具体生产策略可由管理员收紧。",
                ),
                block(
                    "table",
                    headers=["操作", "需要角色", "安全说明"],
                    rows=[
                        ["创建课程", "平台教师或拥有开发 token 的教师", "课程归属当前租户，跨租户访问被拒绝"],
                        ["维护课程成员", "课程教师或助教", "只能给课程内用户设置 `STUDENT`、`TEACHER`、`TA`"],
                        ["创建题目草稿", "课程教师或助教", "Brief 被视为不可信输入，不能覆盖系统指令"],
                        ["审批题目版本", "课程教师或助教", "有 BLOCK 检查项时不能发布"],
                        ["创建作业", "课程教师或助教", "只能引用已发布的 ChallengeVersion"],
                        ["查看 live monitor", "课程教师或助教", "默认不展示学生终端明文"],
                        ["查看成绩", "课程教师或助教", "只能查看本课程 Attempt 的 GradeRevision"],
                        ["复核申诉", "课程教师或助教", "复核会生成审计记录，覆盖成绩会生成新 Revision"],
                    ],
                ),
                block(
                    "note",
                    "教师端不能获得学生容器地址、Pod 名称、sessiond 地址、Kubernetes 凭据、动态 flag、内部 token 或模型密钥。验证报告、监控和成绩页只展示经过平台约束后的状态、证据引用和统计信息。",
                    title="不可突破的边界",
                ),
                block(
                    "bullets",
                    [
                        "不要把题目最终 payload、动态 secret 或教师解法写入 Brief、题目描述、Rubric 解释或公开附件。",
                        "不要根据终端文本直接判定客观通过；客观得分必须来自外部 Oracle 或平台签名事件。",
                        "不要把 live monitor 的辅助状态等同于作弊结论；它只是教学干预信号。",
                        "不要要求学生提交平台 token、浏览器 localStorage 内容或终端票据。",
                    ],
                ),
            ],
        },
        {
            "title": "课前准备与本地实例检查",
            "blocks": [
                block(
                    "p",
                    "上课或演示前，教师应确认控制平面、终端网关、sessiond 和 Web 已启动，并且开发 token 或生产登录方式可用。本地实例的详细启动方式见本仓库运行手册。",
                ),
                block(
                    "steps",
                    [
                        "确认 API 健康检查返回 `{\"ok\":true,\"agentRuntimeEnabled\":false}` 或生产环境的等价健康状态。",
                        "确认 Gateway 健康检查返回 `ok`，并且 API 与 Gateway 使用一致的内部服务 token。",
                        "确认 Web 页面可打开，静态资源没有 chunk 404 或 ChunkLoadError。",
                        "确认教师 token 已写入浏览器 `localStorage.claDevToken`，生产环境则确认 OIDC 登录后具备教师角色。",
                        "打开默认题目验证报告页，确认 `Overall` 不是 `BLOCK`。",
                        "打开默认作业 live monitor，确认页面能加载作业标题和统计卡片。",
                        "抽测一个学生账户创建 Attempt、连接终端、提交答案、生成成绩与申诉。",
                    ],
                ),
                block(
                    "code",
                    """curl --noproxy '*' -sS http://127.0.0.1:8000/healthz
curl --noproxy '*' -sS http://127.0.0.1:8081/healthz
curl --noproxy '*' -I http://127.0.0.1:3000/""",
                ),
                block(
                    "note",
                    "当前本机记录显示 Docker daemon 与 Kubernetes 集群不可用时，不能把 Compose live smoke、真实 K8s NetworkPolicy、gVisor/Kata 或节点故障测试标记为已验证。教师演示可以使用当前本地终端切片，但正式靶场部署仍需要可用容器运行环境。",
                    title="环境限制",
                ),
            ],
        },
        {
            "title": "登录与开发 token 使用",
            "blocks": [
                block(
                    "p",
                    "生产环境应通过学校或平台 OIDC 登录。当前本地开发实例支持 `CLA_DEV_MODE=true` 下的开发 token，用于教师和学生角色测试。",
                ),
                block(
                    "steps",
                    [
                        "在项目根目录生成开发 token。",
                        "复制教师 token。",
                        "打开浏览器控制台，把 token 写入 `localStorage.claDevToken`。",
                        "刷新教师页面，API 请求会自动携带 `Authorization: Bearer <token>`。",
                        "切换学生视角测试时，覆盖为学生 token。",
                    ],
                ),
                block(
                    "code",
                    """PYTHONPATH=services/api/src .venv/bin/python -m cla.dev_tokens

// 在浏览器控制台写入教师 token
localStorage.setItem("claDevToken", "<teacher-token>")

// 清理 token
localStorage.removeItem("claDevToken")""",
                ),
                block(
                    "table",
                    headers=["现象", "可能原因", "处理方式"],
                    rows=[
                        ["页面显示认证失败或 API 返回 401", "未设置 token、token 过期、开发模式未开启", "重新生成 token，确认 `CLA_DEV_MODE=true`"],
                        ["教师页面返回 403", "当前 token 不是课程教师或助教", "检查课程成员或改用教师 token"],
                        ["学生能打开教师页面但接口失败", "页面可路由不代表有权限", "以接口返回为准，确认角色"],
                    ],
                ),
            ],
        },
        {
            "title": "教师端页面入口总览",
            "blocks": [
                block(
                    "p",
                    "当前 Web 首屏是学生工作台，但教师可直接访问教师路由。默认种子数据提供一个 Web SQL 登录题和一个作业，适合用作演示与验收。",
                ),
                block(
                    "table",
                    headers=["页面", "默认示例地址", "用途"],
                    rows=[
                        ["题目验证报告", "`http://127.0.0.1:3000/teacher/challenges/cv_web_sqli_auth_1_3_0/validation`", "查看 ChallengeVersion 的验证结果、风险、证据引用并审批发布"],
                        ["作业实时监控", "`http://127.0.0.1:3000/teacher/assignments/asg_web_sqli_auth/live`", "查看班级 Attempt、LabSession、卡住状态、提示状态和告警计数"],
                        ["学生工作台", "`http://127.0.0.1:3000/`", "教师可用学生 token 进行演示路径验证"],
                        ["学生成绩证据页", "`http://127.0.0.1:3000/student/grades/{attemptId}`", "学生查看成绩；教师通过 API 可查看同一 Attempt 的成绩数据"],
                    ],
                ),
                block(
                    "note",
                    "如果使用 IPv6 地址访问本机 Web，页面会把 API 返回的本地回环 Gateway WebSocket 地址改写为当前页面主机，避免浏览器尝试连接访问者自己的 `127.0.0.1`。",
                    title="IPv6 访问说明",
                ),
            ],
        },
        {
            "title": "课程创建与成员维护",
            "blocks": [
                block(
                    "p",
                    "课程是作业、题目草稿、成员权限和监控范围的上层归属。当前课程与成员维护通过 API 完成。所有写接口应带 `Idempotency-Key` 或遵循接口自身幂等设计，避免刷新或重试创建重复数据。",
                ),
                block(
                    "code",
                    """export CLA_API=http://127.0.0.1:8000
export CLA_TEACHER_TOKEN=<teacher-token>

curl -sS -X POST "$CLA_API/api/v1/courses" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "code": "WEBSEC-101",
    "title": "Web 安全实践",
    "term": "2026 春"
  }'

curl -sS -X PUT "$CLA_API/api/v1/courses/<course-id>/members/<student-user-id>" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"role":"STUDENT"}'""",
                ),
                block(
                    "table",
                    headers=["字段", "含义", "建议"],
                    rows=[
                        ["`code`", "课程代码", "使用学校或课程组统一编码"],
                        ["`title`", "课程名称", "面向学生可读，不写内部管理信息"],
                        ["`term`", "学期或开课周期", "用于归档和过滤"],
                        ["成员 `role`", "`STUDENT`、`TEACHER`、`TA`", "按最小权限分配，助教离课后及时移除"],
                    ],
                ),
            ],
        },
        {
            "title": "Challenge-as-Code 题目包概念",
            "blocks": [
                block(
                    "p",
                    "CLA 的题目采用 Challenge-as-Code。一个题目版本应能被验证、签名、回放和审计。教师不应把题目当作一段普通说明文字，而应把它看作包含目标服务、workspace、策略、Oracle、Rubric 和里程碑的可验证包。",
                ),
                block(
                    "code",
                    """content/challenges/web-sqli-auth/
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
    └── server.py""",
                ),
                block(
                    "bullets",
                    [
                        "`manifest.yaml` 描述题目身份、版本、类别、难度、workspace 类型和资源要求。",
                        "`topology.yaml` 描述 workspace、target 与网络关系。",
                        "`policy/` 描述网络默认拒绝、保留期和安全限制。",
                        "`oracle/` 在学生控制边界外判定客观通过，输出带签名的证据事件。",
                        "`rubric.yaml` 定义每个评分项的分值、证据、评分器类型和版本。",
                        "`milestones.yaml` 用于教学提示和进度判断，但不能泄露最终 payload。",
                    ],
                ),
                block(
                    "note",
                    "一期只支持 `WorkspaceType=TERMINAL`。`REMOTE_DESKTOP` 和 `SIMULATED` 只是类型和 Feature Flag 预留，不应在题目包里引入 RDP/VNC、桌面环境、Guacamole、视觉观察或文档模拟依赖。",
                    title="一期范围",
                ),
            ],
        },
        {
            "title": "从教学 Brief 创建题目草稿",
            "blocks": [
                block(
                    "p",
                    "教师可以用自然语言描述教学目标、题型、难度、预计时长和工具约束。API 会解析成 CourseIntent，并保留低置信字段供教师确认。当前解析和候选重排是确定性和受限 Agent 能力的组合，Agent 不能直接发布题目。",
                ),
                block(
                    "code",
                    """curl -sS -X POST "$CLA_API/api/v1/challenge-drafts" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \\
  -H "Idempotency-Key: brief-20260625-001" \\
  -H "Content-Type: application/json" \\
  -d '{
    "courseId": "<course-id>",
    "brief": "为 Web 安全入门课程创建一个 45 分钟的 SQL 注入登录绕过实践，学生使用浏览器终端和 curl，要求外部 Oracle 判定通过，不泄露最终 payload。",
    "constraints": {
      "workspaceType": "TERMINAL",
      "maxMinutes": 45,
      "difficulty": 2
    }
  }'""",
                ),
                block(
                    "table",
                    headers=["返回字段", "教师需要看什么"],
                    rows=[
                        ["`draftId`", "后续查询候选和 materialize 时使用"],
                        ["`courseIntent.category`", "题目类别是否符合课程目标"],
                        ["`courseIntent.target`", "目标服务或技能点是否正确"],
                        ["`courseIntent.difficulty`", "难度是否符合学生基础"],
                        ["`courseIntent.expectedMinutes`", "预计时长是否适合课堂安排"],
                        ["`courseIntent.uncertainFields`", "需要教师重点确认的字段"],
                        ["`candidatesUrl`", "候选题检索接口地址"],
                    ],
                ),
                block(
                    "note",
                    "Brief 中不要写动态 flag、教师解法、最终 payload 或真实凭据。Brief 是不可信输入，即使内容看似是系统指令，也不能改变平台权限和评分规则。",
                    title="Brief 安全要求",
                ),
            ],
        },
        {
            "title": "候选题检索与选择",
            "blocks": [
                block(
                    "p",
                    "草稿创建后，教师查询候选题。平台会对 workspace 类型、风险等级、验证状态和教学目标做硬过滤，并返回匹配原因和冲突说明。教师应选择验证状态可接受、风险等级合适、目标明确的候选题。",
                ),
                block(
                    "code",
                    """curl -sS "$CLA_API/api/v1/challenge-drafts/<draft-id>/candidates" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" """,
                ),
                block(
                    "table",
                    headers=["字段", "含义", "选择建议"],
                    rows=[
                        ["`candidateId`", "候选记录 ID", "materialize 时使用"],
                        ["`challengeVersionId`", "候选题版本", "确认不是旧版或未验证版本"],
                        ["`score`", "匹配分数", "不是唯一标准，要结合 matchReasons 和 conflicts"],
                        ["`constraintsSatisfied`", "是否满足硬约束", "为 false 时不应选择"],
                        ["`matchReasons`", "匹配原因", "用于解释为什么适合本节课"],
                        ["`conflicts`", "冲突点", "冲突为安全边界或时间限制时不要发布"],
                        ["`validationStatus`", "内容验证状态", "发布前必须有验证报告"],
                    ],
                ),
                block(
                    "bullets",
                    [
                        "优先选择与课程目标完全匹配且已有验证报告的候选。",
                        "如果候选冲突是工具缺失、时间超限或风险等级过高，应修改 Brief 或新增题目包。",
                        "如果多个候选都可用，选择教学证据更完整、Rubric 更清晰的版本。",
                    ],
                ),
            ],
        },
        {
            "title": "Materialize 题目版本并生成验证报告",
            "blocks": [
                block(
                    "p",
                    "Materialize 会把草稿选择落到一个待审批的 ChallengeVersion，并关联内容验证运行。这个步骤是草稿进入可发布版本的边界。已 materialize 的草稿不能随意换候选，否则 API 会返回冲突。",
                ),
                block(
                    "code",
                    """curl -sS -X POST "$CLA_API/api/v1/challenge-drafts/<draft-id>/materialize" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"selectedCandidateId":"<candidate-id>"}'""",
                ),
                block(
                    "table",
                    headers=["返回字段", "用途"],
                    rows=[
                        ["`challengeVersionId`", "验证报告和审批发布使用"],
                        ["`versionStatus`", "确认是待审批还是已发布"],
                        ["`validationRunId`", "定位验证运行"],
                        ["`validationStatus`", "判断是否有 BLOCK/WARN"],
                        ["`validationReportUrl`", "教师打开验证报告的 API 路径"],
                        ["`approvalRequired`", "是否还需要教师审批"],
                    ],
                ),
            ],
        },
        {
            "title": "题目验证报告页使用方法",
            "blocks": [
                block(
                    "p",
                    "验证报告页是教师发布题目前最重要的页面。它展示 ChallengeVersion 的总体状态、检查摘要、验证元数据、分组检查项、证据引用和已检查的禁止泄露类别。",
                ),
                block(
                    "steps",
                    [
                        "打开 `/teacher/challenges/{versionId}/validation`。",
                        "查看顶部 `Overall`，只有 `PASS` 或可接受的 `WARN` 才能继续审批；`BLOCK` 必须先修复题目。",
                        "查看 `Pass`、`Warn`、`Block` 计数，确认 Block 为 0。",
                        "查看 `Artifact`，确认题目包 digest 与待发布版本一致。",
                        "查看 `Workflow`、`Started`、`Ended`，确认验证不是旧报告。",
                        "逐组展开检查项，关注 `SCHEMA`、`BUILD`、`SCAN`、`RUNTIME`、`SOLVE`、`ORACLE`、`RESOURCE`、`TUTOR`、`WORKSPACE` 等类别。",
                        "查看每个检查项的 evidence refs。证据引用缺失或含义不清时，不应发布。",
                        "检查 Forbidden disclosure classes，确认动态 secret、最终 payload、教师解法、token 等类别都已纳入扫描。",
                        "点击 `刷新` 获取最新报告。",
                    ],
                ),
                block(
                    "table",
                    headers=["状态", "含义", "教师处理"],
                    rows=[
                        ["`PASS`", "检查通过", "可进入审批判断"],
                        ["`WARN`", "发现警告但不阻断", "阅读证据，确认是否可在课堂中接受"],
                        ["`BLOCK`", "阻断发布", "必须修复题目包或策略后重新验证"],
                    ],
                ),
                block(
                    "note",
                    "验证报告不是教师解法页。报告中不应出现最终 payload、动态 secret、真实学生终端明文或控制平面凭据。如果看到这类内容，应停止发布并修复内容验证规则。",
                    title="报告内容边界",
                ),
            ],
        },
        {
            "title": "审批发布 ChallengeVersion",
            "blocks": [
                block(
                    "p",
                    "题目版本只有审批发布后才能被作业引用。页面右上角的 `审批发布` 按钮会调用发布接口。版本已发布后按钮显示 `已发布`，再次点击不会重复发布。",
                ),
                block(
                    "steps",
                    [
                        "确认验证报告 `Block` 为 0。",
                        "确认所有 `WARN` 已阅读，且不影响安全、评分或课堂可用性。",
                        "确认题目没有 GUI/RDP/VNC 依赖，workspace type 是 `TERMINAL`。",
                        "确认 Oracle 正例和负例都通过验证，不能被学生伪造。",
                        "确认 Rubric 每个 criterion 有稳定证据引用。",
                        "点击 `审批发布`。",
                        "看到 `审批已发布` 或 `版本已发布` 后刷新页面。",
                    ],
                ),
                block(
                    "code",
                    """curl -sS -X POST "$CLA_API/api/v1/challenge-versions/<version-id>/approve" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" """,
                ),
                block(
                    "note",
                    "发布后的 ChallengeVersion 应视为不可变。修改 manifest、topology、policy、rubric、Oracle、target 行为、workspace 工具或镜像 digest 都应创建新版本。",
                    title="版本不可变",
                ),
            ],
        },
        {
            "title": "创建作业与发布给学生",
            "blocks": [
                block(
                    "p",
                    "作业把课程、已发布 ChallengeVersion、开放时间、截止时间和尝试策略绑定在一起。当前作业创建通过 API 完成。学生工作台默认使用环境变量中的 `NEXT_PUBLIC_CLA_ASSIGNMENT_ID`，本地默认是 `asg_web_sqli_auth`。",
                ),
                block(
                    "code",
                    """curl -sS -X POST "$CLA_API/api/v1/assignments" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \\
  -H "Idempotency-Key: assignment-20260625-001" \\
  -H "Content-Type: application/json" \\
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
  }'""",
                ),
                block(
                    "table",
                    headers=["字段", "说明", "注意事项"],
                    rows=[
                        ["`courseId`", "所属课程", "教师必须是该课程教师或助教"],
                        ["`challengeVersionId`", "题目版本", "必须是已发布版本"],
                        ["`title`", "学生看到的作业名", "不写最终解法或 secret"],
                        ["`openAt`", "开放时间", "为空时默认当前时间"],
                        ["`dueAt`", "截止时间", "为空表示未设置截止"],
                        ["`attemptPolicy.maxAttempts`", "尝试次数", "本地默认 1"],
                        ["`attemptPolicy.maxResets`", "重置次数", "用于限制环境重置频率"],
                    ],
                ),
            ],
        },
        {
            "title": "作业实时监控页使用方法",
            "blocks": [
                block(
                    "p",
                    "作业实时监控页用于课堂中观察整体状态，而不是观看学生终端明文。它帮助教师发现环境未就绪、疑似卡住、资源或安全告警等情况，并决定是否进行课堂干预。",
                ),
                block(
                    "steps",
                    [
                        "打开 `/teacher/assignments/{assignmentId}/live`。",
                        "查看页面标题确认进入正确作业。",
                        "查看 `更新` 时间，必要时点击 `刷新`。",
                        "查看顶部统计卡：Attempts、Ready、Stuck、Resource、Security。",
                        "在会话表中查看每个学生的 Attempt ID、session 状态、epoch、辅助状态、最近提示和最近事件时间。",
                        "优先处理 Resource 或 Security 告警数量较高的学生。",
                        "对 `CONFIRMED` 或高分疑似卡住学生，可先线下询问，不要直接给最终 payload。",
                    ],
                ),
                block(
                    "table",
                    headers=["字段", "含义", "教师动作"],
                    rows=[
                        ["`Attempts`", "作业下 Attempt 总数", "确认学生是否都已开始"],
                        ["`Ready`", "已就绪 LabSession 数", "低于预期时检查环境"],
                        ["`Stuck`", "疑似卡住数量", "用于安排提醒或巡查"],
                        ["`Resource`", "资源类告警", "检查容器、配额或长输出"],
                        ["`Security`", "安全类告警", "检查策略事件，但不能直接判作弊"],
                        ["`sessionStatus`", "单个会话状态", "`READY` 表示终端环境可用"],
                        ["`latestHint`", "最近提示等级与状态", "判断学生是否已收到辅助"],
                    ],
                ),
                block(
                    "note",
                    "live monitor 默认不展示完整终端明文。终端文本属于学生可控弱证据，系统只在证据页和审计链中引用经过策略处理的事件和片段引用。",
                    title="隐私与证据边界",
                ),
            ],
        },
        {
            "title": "查看学生成绩证据",
            "blocks": [
                block(
                    "p",
                    "学生提交后，系统会创建不可变 GradeRevision。教师可通过 API 查看课程内 Attempt 的最新成绩。成绩由总分、独立完成指数、Rubric 版本、Grader 版本和 CriterionResult 组成。",
                ),
                block(
                    "code",
                    """curl -sS "$CLA_API/api/v1/attempts/<attempt-id>/grade" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" """,
                ),
                block(
                    "table",
                    headers=["字段", "含义", "教学用途"],
                    rows=[
                        ["`totalScore`", "总分", "对学生正式成绩的核心显示值"],
                        ["`independenceIndex`", "独立完成指数", "提示使用和辅助依赖的说明指标，不改变总分"],
                        ["`revisionNo`", "成绩修订号", "申诉覆盖后递增"],
                        ["`rubricVersion`", "评分标准版本", "追溯本次评分依据"],
                        ["`graderVersion`", "评分器版本", "追溯自动评分实现"],
                        ["`criteria[].criterionId`", "评分项 ID", "申诉和覆盖时按项处理"],
                        ["`criteria[].score/maxScore`", "单项得分", "定位失分点"],
                        ["`criteria[].graderType`", "评分类型", "区分 Oracle、事件模式和开放评价"],
                        ["`criteria[].confidence`", "置信度", "低置信应人工复核"],
                        ["`criteria[].evidenceRefs`", "证据引用", "判断分数是否可追溯"],
                    ],
                ),
                block(
                    "note",
                    "教师复核时应围绕 evidence refs 和 Rubric 解释讨论，不应要求学生提供动态 token、终端票据或系统内部路由。",
                    title="复核材料边界",
                ),
            ],
        },
        {
            "title": "申诉复核与教师覆盖成绩",
            "blocks": [
                block(
                    "p",
                    "学生在成绩证据页按 criterion 提交申诉后，教师可复核。复核结果可以维持原成绩，也可以覆盖指定 criterion 分数。覆盖不会修改旧 GradeRevision，而是生成新的 GradeRevision，保留原始记录和审计链。",
                ),
                block(
                    "code",
                    """# 维持原成绩
curl -sS -X POST "$CLA_API/api/v1/appeals/<appeal-id>/resolve" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "decision": "UPHOLD_ORIGINAL",
    "resolution": "Oracle 证据和 Rubric 解释一致，维持原评分。",
    "criterionOverrides": []
  }'

# 覆盖某个评分项
curl -sS -X POST "$CLA_API/api/v1/appeals/<appeal-id>/resolve" \\
  -H "Authorization: Bearer $CLA_TEACHER_TOKEN" \\
  -H "Content-Type: application/json" \\
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
  }'""",
                ),
                block(
                    "bullets",
                    [
                        "只能复核状态为 `OPEN` 的 Appeal。",
                        "`OVERRIDE_SCORE` 必须覆盖学生申诉的那个 criterion，否则 API 会拒绝。",
                        "覆盖分数不能超过该 criterion 的 `maxScore`。",
                        "复核说明 `resolution` 应写清事实依据、引用证据和最终决定。",
                        "如果需要调整多个相关 criterion，应确保每个 criterion 都存在于原 GradeRevision 中。",
                    ],
                ),
            ],
        },
        {
            "title": "课堂辅助信号的解释方式",
            "blocks": [
                block(
                    "p",
                    "CLA 的 Tutor 侧重教学辅助。系统会根据重复命令、相同错误、里程碑停滞、探索新颖度、长任务排除等特征判断学生是否可能卡住，并提供 L1 到 L3 分级提示。",
                ),
                block(
                    "table",
                    headers=["状态或字段", "含义", "教师解释"],
                    rows=[
                        ["`NORMAL`", "未发现明显卡住", "无需干预，继续观察"],
                        ["`SUSPECTED`", "疑似卡住", "可提醒学生查看题目目标或请求 L1 提示"],
                        ["`CONFIRMED`", "卡住概率高", "可进行非答案式引导"],
                        ["`score`", "卡住评分", "不是成绩分，也不是作弊概率"],
                        ["`latestHint.level`", "最近提示等级", "L1 最轻，L3 更具体"],
                        ["`AUTO_DISABLED`", "学生关闭自动提示", "尊重学生选择，不因此扣分"],
                    ],
                ),
                block(
                    "note",
                    "提示使用只影响独立完成指数，不直接改变总分。教师应把该指数作为学习过程参考，而不是单独惩罚依据。",
                    title="独立完成指数",
                ),
            ],
        },
        {
            "title": "题目发布前安全检查清单",
            "blocks": [
                block(
                    "checklist",
                    [
                        "题目版本 workspace type 为 `TERMINAL`。",
                        "题目包没有 GUI、RDP、VNC、Guacamole、桌面环境或视觉模型依赖。",
                        "没有 privileged、hostPath、hostNetwork、hostPID 或自动挂载 ServiceAccount token。",
                        "网络策略默认拒绝，只放行 workspace 到 target 的必要端口以及 Gateway 到 sessiond 的路径。",
                        "manifest、rubric、日志、验证报告和公开附件中没有动态 secret、最终 payload 或教师解法。",
                        "Oracle 在学生 workspace 外运行，并且正例和负例都通过验证。",
                        "Rubric 每个 criterion 有分值、解释、证据引用和评分器版本。",
                        "Shell hook、Tutor 或 Agent 不可用时，学生仍可使用终端和客观评分。",
                        "发布前验证报告没有 BLOCK，所有 WARN 都已人工确认。",
                        "状态文档记录了本次实际运行命令、测试结果和已知限制。",
                    ],
                ),
            ],
        },
        {
            "title": "教师端常见问题与处理",
            "blocks": [
                block(
                    "table",
                    headers=["问题", "可能原因", "处理步骤"],
                    rows=[
                        ["验证报告页面加载失败", "token 缺失、无课程权限、versionId 错误或 API 未启动", "检查 localStorage、API healthz 和版本 ID"],
                        ["审批按钮不可用", "报告为 BLOCK、版本已发布或验证报告不存在", "先修复题目并重新验证，已发布版本无需再次审批"],
                        ["作业创建返回 `CHALLENGE_VERSION_NOT_PUBLISHED`", "引用了未发布版本", "先进入验证报告页审批发布"],
                        ["live monitor 没有会话", "学生尚未创建 Attempt 或 assignmentId 错误", "让学生点击启动，确认作业 ID"],
                        ["学生终端票据被拒", "票据超过 60 秒、nonce 重放、Gateway 与 API token 不一致", "让学生重新点击启动或重连，检查 Gateway 配置"],
                        ["成绩不存在", "学生未提交、评分流程未完成或 attemptId 错误", "确认学生已点击提交并刷新成绩"],
                        ["申诉复核失败", "Appeal 非 OPEN、覆盖项不是被申诉项、分数超过 maxScore", "按接口错误码修正请求"],
                        ["Docker/Compose live smoke 不能运行", "本机 Docker daemon 不可用", "只能标记静态配置验证，不能标记 live 验证完成"],
                    ],
                ),
            ],
        },
        {
            "title": "教师端 API 速查",
            "blocks": [
                block(
                    "table",
                    headers=["功能", "方法与路径", "说明"],
                    rows=[
                        ["当前用户", "`GET /api/v1/me`", "查看登录身份和角色上下文"],
                        ["创建课程", "`POST /api/v1/courses`", "创建课程"],
                        ["维护成员", "`PUT /api/v1/courses/{courseId}/members/{userId}`", "设置课程角色"],
                        ["创建题目草稿", "`POST /api/v1/challenge-drafts`", "从 Brief 生成 CourseIntent"],
                        ["查看候选", "`GET /api/v1/challenge-drafts/{draftId}/candidates`", "检索候选题"],
                        ["生成版本", "`POST /api/v1/challenge-drafts/{draftId}/materialize`", "选择候选并生成待审批版本"],
                        ["查看验证", "`GET /api/v1/challenge-versions/{versionId}/validation`", "读取验证报告"],
                        ["审批发布", "`POST /api/v1/challenge-versions/{versionId}/approve`", "发布题目版本"],
                        ["创建作业", "`POST /api/v1/assignments`", "引用已发布版本创建作业"],
                        ["实时监控", "`GET /api/v1/assignments/{assignmentId}/live`", "教师 live monitor 数据"],
                        ["查看成绩", "`GET /api/v1/attempts/{attemptId}/grade`", "查看最新 GradeRevision"],
                        ["复核申诉", "`POST /api/v1/appeals/{appealId}/resolve`", "维持或覆盖成绩"],
                    ],
                ),
                block(
                    "note",
                    "内部接口 `/internal/...` 仅供 Gateway、sessiond、Oracle、环境控制器等可信服务调用，教师日常使用不应直接调用。",
                    title="内部接口",
                ),
            ],
        },
    ]
    return Manual(
        slug="teacher-guide",
        title="CyberLab Assistant（CLA）教师端使用手册",
        subtitle="题目维护、验证发布、作业监控、成绩证据与申诉复核",
        audience="教师、助教、内容工程师、课程专家",
        pdf_name="cla-teacher-guide.pdf",
        sections=sections,
    )


def student_manual() -> Manual:
    sections = [
        {
            "title": "文档定位与学习路径",
            "blocks": [
                block(
                    "p",
                    "本文是 CyberLab Assistant（CLA）学生端使用手册，面向参加网安实践课程的学生。它从登录、启动实验、使用浏览器终端、请求提示、提交答案、查看成绩到提交申诉，按完整学习流程说明每一步。",
                ),
                block(
                    "note",
                    "当前学生端是终端优先的一期实现。你会在浏览器中看到 xterm.js 终端，连接到属于自己 Attempt 的隔离 LabSession。平台不会把容器地址、内部路由或 sessiond 地址暴露给浏览器。",
                    title="你将使用什么",
                ),
                block(
                    "steps",
                    [
                        "登录或写入开发 token。",
                        "打开学生工作台。",
                        "点击 `启动` 创建 Attempt 和终端会话。",
                        "在浏览器终端中完成实践任务。",
                        "必要时请求 L1、L2、L3 分级提示。",
                        "在右侧提交区填写根因解释并提交。",
                        "查看成绩证据页，理解每个评分项。",
                        "如有充分理由，选择具体评分项提交申诉。",
                    ],
                ),
            ],
        },
        {
            "title": "登录、token 与页面入口",
            "blocks": [
                block(
                    "p",
                    "生产环境通常通过学校或平台统一登录。当前本地开发实例使用 `claDevToken` 模拟学生身份。教师或管理员会提供学生 token。",
                ),
                block(
                    "steps",
                    [
                        "打开 `http://127.0.0.1:3000`。",
                        "如果是开发模式，打开浏览器控制台。",
                        "执行 `localStorage.setItem(\"claDevToken\", \"<student-token>\")`。",
                        "刷新页面。",
                        "页面顶部当前 Attempt 显示 `未创建` 时，说明还没有开始本次作业。",
                    ],
                ),
                block(
                    "code",
                    """// 写入学生 token
localStorage.setItem("claDevToken", "<student-token>")

// 查看当前 token
localStorage.getItem("claDevToken")

// 清理 token
localStorage.removeItem("claDevToken")""",
                ),
                block(
                    "table",
                    headers=["入口", "路径", "用途"],
                    rows=[
                        ["学生工作台", "`/`", "启动实验、连接终端、请求提示、提交答案、查看简要成绩"],
                        ["完整成绩证据页", "`/student/grades/{attemptId}`", "查看总分、独立完成指数、每项证据和申诉入口"],
                    ],
                ),
                block(
                    "note",
                    "不要把自己的 token 发给同学，也不要把 token 写进提交答案、终端命令或截图。开发 token 只用于本地环境，正式课程以管理员说明为准。",
                    title="身份安全",
                ),
            ],
        },
        {
            "title": "学生工作台布局",
            "blocks": [
                block(
                    "p",
                    "学生工作台分为左侧导航、中间终端区域和右侧辅助/提交/成绩区域。页面使用中文按钮，少数状态字段保留英文状态码，便于和系统日志、教师监控一致。",
                ),
                block(
                    "table",
                    headers=["区域", "你会看到", "用途"],
                    rows=[
                        ["左侧导航", "`Terminal`、`Evidence`、`Appeal`", "当前主要使用 Terminal；Evidence 和 Appeal 对应成绩和申诉流程"],
                        ["顶部状态栏", "当前 Attempt、连接状态、session/epoch", "确认自己是否已创建 Attempt、终端是否连接"],
                        ["中间终端", "黑色终端窗口", "输入命令、运行工具、观察输出"],
                        ["底部操作", "`启动`、`重连`、`重置`", "创建或恢复会话，必要时重置实验环境"],
                        ["右侧辅助", "状态、L1/L2/L3 按钮、最近提示、反馈按钮", "请求或管理教学提示"],
                        ["右侧提交", "答案文本框、`提交` 按钮", "提交根因解释和开放答案"],
                        ["右侧成绩证据", "Total、各 criterion 简要分数、完整证据页链接", "提交后快速查看成绩摘要"],
                    ],
                ),
                block(
                    "note",
                    "提示和平台状态不会抢占终端焦点。终端连接成功后，光标通常在终端内，可以直接输入命令。",
                    title="焦点行为",
                ),
            ],
        },
        {
            "title": "启动 Attempt 与 LabSession",
            "blocks": [
                block(
                    "p",
                    "Attempt 表示你对某个作业的一次实践记录。LabSession 表示本次 Attempt 对应的隔离实验环境。点击 `启动` 后，系统会创建 Attempt、创建或确保 LabSession、签发一次性终端票据，并连接 Gateway。",
                ),
                block(
                    "steps",
                    [
                        "确认页面已经登录，右上或顶部没有认证错误。",
                        "点击 `启动`。",
                        "状态从 `idle` 变成 `provisioning`，表示正在准备环境。",
                        "环境就绪后，状态变成 `connected`。",
                        "顶部会显示 Attempt ID，以及 session ID 和 epoch。",
                        "终端出现 shell 提示符后即可输入命令。",
                    ],
                ),
                block(
                    "table",
                    headers=["状态", "含义", "你应该做什么"],
                    rows=[
                        ["`idle`", "未开始或当前没有连接", "点击 `启动`"],
                        ["`provisioning`", "正在创建 Attempt、会话或票据", "等待，不要反复点击"],
                        ["`connected`", "终端已连接", "开始实践"],
                        ["`closed`", "WebSocket 关闭", "点击 `重连`"],
                        ["`error`", "连接或 API 出错", "查看页面错误信息，必要时刷新或联系教师"],
                    ],
                ),
                block(
                    "note",
                    "终端票据是 60 秒内有效的一次性票据，绑定 user、attempt、session epoch、audience、nonce 和过期时间。你不需要也不应该手动复制或保存它。",
                    title="一次性票据",
                ),
            ],
        },
        {
            "title": "使用浏览器终端",
            "blocks": [
                block(
                    "p",
                    "终端是你完成实践的主要工具。它通过二进制 WebSocket 与 Gateway 通信，支持 UTF-8、resize、heartbeat、ACK 和短时间重连 replay。",
                ),
                block(
                    "bullets",
                    [
                        "输入命令后按 Enter 执行。",
                        "调整浏览器窗口大小时，页面会向服务端发送 resize。",
                        "终端输出很多时，浏览器会进行流控；不要把超大二进制内容直接打印到终端。",
                        "如果网络短暂断开，重连时会携带最后收到的 server sequence，Gateway 尝试回放缓冲输出。",
                        "不要在终端里输出自己的 token、个人密码、浏览器 localStorage 或其他敏感信息。",
                    ],
                ),
                block(
                    "code",
                    """# 示例：确认 shell 可用
pwd
whoami
ls

# 示例：访问题目目标，具体目标地址以题目说明为准
curl -i http://target:8080/""",
                ),
                block(
                    "note",
                    "终端文本会被视为不可信数据。它可以辅助教学和证据引用，但正式客观通过依赖学生控制边界外的 Oracle 或平台签名事件。",
                    title="终端证据边界",
                ),
            ],
        },
        {
            "title": "重连与重置",
            "blocks": [
                block(
                    "p",
                    "`重连` 和 `重置` 是两个不同动作。重连保留当前 LabSession 和 session epoch，只重新获取票据并连接终端。重置会创建新的 session epoch，旧票据和旧路由失效。",
                ),
                block(
                    "table",
                    headers=["按钮", "会发生什么", "适用场景", "风险"],
                    rows=[
                        ["`重连`", "复用当前 Attempt 和 LabSession，重新签发终端票据", "网络断开、页面刷新、状态为 closed", "通常不会清空实验状态"],
                        ["`重置`", "重置当前 Attempt 的实验会话，session epoch 递增", "环境损坏、命令误操作导致无法继续", "可能清空当前环境状态，且可能受次数限制"],
                    ],
                ),
                block(
                    "steps",
                    [
                        "看到 `closed` 时，先点击 `重连`。",
                        "看到 `error` 且错误与票据过期、nonce 重放或网络断开有关，也先尝试 `重连`。",
                        "只有当环境状态被破坏、目标无法恢复或教师建议时，再点击 `重置`。",
                        "重置后等待状态回到 `connected`，不要继续使用旧页面里保存的任何票据信息。",
                    ],
                ),
            ],
        },
        {
            "title": "任务完成方式与提交前检查",
            "blocks": [
                block(
                    "p",
                    "不同题目有不同目标。以默认 Web SQL 登录题为例，你需要通过终端工具分析目标行为，完成要求的状态改变或验证目标，然后提交根因解释。不要把最终 payload 当成唯一答案，成绩通常同时看客观 Oracle 与解释质量。",
                ),
                block(
                    "checklist",
                    [
                        "已阅读题目目标和允许工具。",
                        "已确认当前终端属于自己的 Attempt。",
                        "已完成题目要求的客观动作，例如触发目标状态、访问验证端点或完成指定操作。",
                        "已记录关键观察，例如输入与输出的差异、错误信息、服务行为变化。",
                        "已理解根因，而不是只复制某条命令。",
                        "没有在答案中写入 token、动态 secret、他人信息或平台内部地址。",
                        "如使用了提示，已理解提示内容，并能用自己的话解释。",
                    ],
                ),
                block(
                    "note",
                    "如果题目明确要求不要泄露最终 payload 或动态 secret，答案中也不应该出现这些内容。可以描述漏洞类型、验证思路、影响和修复建议。",
                    title="答案内容边界",
                ),
            ],
        },
        {
            "title": "使用 L1、L2、L3 分级提示",
            "blocks": [
                block(
                    "p",
                    "右侧辅助面板提供 L1、L2、L3 三个等级。它们用于在你卡住时提供不同粒度的帮助。系统也可能根据卡住检测状态主动生成提示，但你可以反馈或关闭自动提示。",
                ),
                block(
                    "table",
                    headers=["等级", "典型内容", "何时使用"],
                    rows=[
                        ["`L1`", "方向性提醒，例如检查目标、阅读错误、回顾概念", "刚开始不确定下一步时"],
                        ["`L2`", "更具体的排查路径，例如建议尝试某类请求或观察某类响应", "尝试多次仍无法定位时"],
                        ["`L3`", "接近操作层面的强提示，但不应泄露最终 payload 或动态 secret", "临近截止或长期卡住时"],
                    ],
                ),
                block(
                    "steps",
                    [
                        "点击 L1、L2 或 L3。",
                        "查看提示卡片中的等级、状态、tutor version 和内容。",
                        "查看 evidence refs，理解系统为什么给出这个提示。",
                        "如果提示有帮助，点击 `接受`。",
                        "如果暂时不需要，点击 `稍后`。",
                        "如果你认为系统误判卡住，点击 `这不是卡住`。",
                        "如果不想再收到自动提示，点击 `关闭自动提示`。",
                    ],
                ),
                block(
                    "note",
                    "提示使用只影响独立完成指数，不直接改变总分。独立完成指数用于呈现学习过程依赖程度，不是单独扣分按钮。",
                    title="提示与成绩",
                ),
            ],
        },
        {
            "title": "理解辅助状态",
            "blocks": [
                block(
                    "p",
                    "辅助面板会显示当前卡住评估状态和分数。这个分数表示卡住可能性，不是作业成绩，也不是作弊判断。",
                ),
                block(
                    "table",
                    headers=["状态", "含义", "建议"],
                    rows=[
                        ["`NORMAL`", "系统未发现明显卡住迹象", "继续实践"],
                        ["`SUSPECTED`", "系统发现一些卡住特征", "可以先请求 L1 或重新检查题目目标"],
                        ["`CONFIRMED`", "系统认为卡住可能较高", "请求更高等级提示，或向教师说明你已经尝试过什么"],
                        ["自动提示开启", "系统可能主动展示提示", "可按需反馈"],
                        ["自动提示已关闭", "系统不再主动提示", "仍可手动点击 L1/L2/L3"],
                    ],
                ),
                block(
                    "bullets",
                    [
                        "重复同一条失败命令可能提高卡住评分。",
                        "长时间运行的正常任务会被排除，系统不应仅因等待而判定卡住。",
                        "探索新的命令、观察新响应和达成里程碑通常会降低卡住风险。",
                        "如果系统提示不符合你的实际情况，使用反馈按钮比忽略更有价值。",
                    ],
                ),
            ],
        },
        {
            "title": "提交答案",
            "blocks": [
                block(
                    "p",
                    "完成实践后，在右侧 `提交` 区域填写答案。当前默认提交一个 `root-cause` 问题，格式为 Markdown。提交后系统会请求 Oracle 检查并生成 GradeRevision。",
                ),
                block(
                    "steps",
                    [
                        "在答案文本框中写清楚漏洞或问题的根因。",
                        "说明你如何验证该根因，例如关键请求、响应差异或目标状态变化。",
                        "说明影响和修复建议，如果题目要求。",
                        "确认答案中没有 token、动态 secret 或平台内部地址。",
                        "点击 `提交`。",
                        "等待成绩摘要出现。如果暂时显示 `no grade`，可稍后刷新或进入完整证据页。",
                    ],
                ),
                block(
                    "table",
                    headers=["好答案通常包含", "不建议包含"],
                    rows=[
                        ["漏洞类型和触发条件", "无关的终端大段输出"],
                        ["关键观察和验证方法", "未脱敏的 token、Cookie、Authorization"],
                        ["为什么这个操作证明问题存在", "同学的答案或他人信息"],
                        ["修复思路或防护建议", "动态 flag 或题目明确禁止公开的 payload"],
                    ],
                ),
            ],
        },
        {
            "title": "成绩摘要与完整证据页",
            "blocks": [
                block(
                    "p",
                    "提交后，工作台右侧会显示 Total 和每个 criterion 的简要分数。点击 `完整证据页` 进入更详细页面。完整证据页是你理解成绩和申诉的主要依据。",
                ),
                block(
                    "steps",
                    [
                        "在工作台右侧找到 `成绩证据`。",
                        "查看 Total 总分。",
                        "查看每个 criterion 的简要得分。",
                        "点击 `完整证据页`。",
                        "在新页面查看总分、独立完成指数、Attempt、Revision、Rubric、Grader 和 Published。",
                        "逐项点击 criterion，阅读得分、评分类型、置信度、解释和 evidence refs。",
                    ],
                ),
                block(
                    "table",
                    headers=["字段", "含义", "你应该关注什么"],
                    rows=[
                        ["`总分`", "本次最新 GradeRevision 的总分", "是否符合预期"],
                        ["`独立完成指数`", "提示依赖程度指标", "理解自己的求助情况"],
                        ["`Revision`", "成绩修订号和状态", "申诉后可能递增"],
                        ["`Rubric`", "评分标准版本", "不同版本不可混淆"],
                        ["`Grader`", "评分器版本", "用于复现和排错"],
                        ["`criterionId`", "评分项 ID", "申诉时必须选择具体项"],
                        ["`score/maxScore`", "单项得分", "定位失分点"],
                        ["`graderType`", "评分方式", "Oracle、事件模式或开放评价"],
                        ["`confidence`", "置信度", "低置信可请求教师复核"],
                        ["`evidenceRefs`", "证据引用", "判断评分是否有依据"],
                    ],
                ),
            ],
        },
        {
            "title": "提交申诉",
            "blocks": [
                block(
                    "p",
                    "如果你认为某个评分项有误，可以在完整证据页右侧提交申诉。申诉必须针对具体 criterion，不能只写“分数不对”。",
                ),
                block(
                    "steps",
                    [
                        "打开完整成绩证据页。",
                        "在右侧 `申诉` 面板中选择要申诉的标准。",
                        "阅读该标准当前分数、评分类型和 evidence refs。",
                        "在理由框中写明具体原因，至少 3 个字符。",
                        "说明你认为哪个证据遗漏、哪条解释不准确、或哪个评分项应如何调整。",
                        "点击 `提交申诉`。",
                        "看到 `OPEN` 状态和 Appeal ID 后，等待教师复核。",
                    ],
                ),
                block(
                    "table",
                    headers=["有效申诉", "无效或低质量申诉"],
                    rows=[
                        ["指出具体 criterion 和证据引用", "只写“老师我应该满分”"],
                        ["说明实际完成步骤与证据之间的关系", "粘贴无关终端输出"],
                        ["解释为什么评分解释与事实不一致", "要求系统泄露 Oracle 或标准答案"],
                        ["提供可复核的观察和时间点", "包含 token、Cookie 或他人信息"],
                    ],
                ),
                block(
                    "note",
                    "教师复核如果覆盖成绩，会生成新的 GradeRevision，旧成绩不会被删除。你之后看到的 Revision 可能递增。",
                    title="复核结果",
                ),
            ],
        },
        {
            "title": "隐私、诚信与安全使用",
            "blocks": [
                block(
                    "p",
                    "CLA 的目标是帮助你在隔离环境中学习真实安全实践。平台会收集必要的事件、证据引用和评分信息，但不应公开你的完整终端明文。你也需要遵守课程规则和安全边界。",
                ),
                block(
                    "bullets",
                    [
                        "只在平台分配给你的 Attempt 中操作，不尝试访问他人的 Attempt、课程或会话。",
                        "不要攻击平台控制平面、教师页面、Gateway、sessiond、API 或身份系统。",
                        "不要尝试复用、篡改或分享终端票据。",
                        "不要把 token、Cookie、Authorization、动态 flag 或个人密码写进答案。",
                        "不要把题目最终 payload 在公共渠道传播，除非教师明确允许。",
                        "不要把系统辅助状态当作成绩本身；它是教学过程信号。",
                        "发现平台漏洞或越权风险时，立即报告教师或管理员。",
                    ],
                ),
                block(
                    "note",
                    "终端、网页、附件和学生答案中的自然语言都被平台视为不可信数据。它们不能改变系统指令、工具权限或评分规则。",
                    title="Prompt Injection 边界",
                ),
            ],
        },
        {
            "title": "常见问题与排障",
            "blocks": [
                block(
                    "table",
                    headers=["问题", "可能原因", "处理方式"],
                    rows=[
                        ["页面显示 API 认证失败", "未写入 token 或 token 不是学生角色", "重新写入学生 token，刷新页面"],
                        ["点击启动后一直 `provisioning`", "环境启动慢、API 或 sessiond 不可用", "等待一会儿，仍失败则联系教师"],
                        ["状态变成 `closed`", "WebSocket 关闭或网络中断", "点击 `重连`"],
                        ["状态变成 `error`", "票据过期、nonce 重放、Gateway 不通或 API 错误", "刷新页面后重连，记录错误码给教师"],
                        ["终端没有输出", "Gateway 未连接 sessiond、shell 未启动或浏览器连接异常", "先重连，再联系教师检查服务"],
                        ["点击提交后没有成绩", "评分还没完成、Oracle 未产生证据或网络错误", "等待后刷新，必要时联系教师"],
                        ["成绩页显示暂无成绩", "Attempt ID 错误或尚未提交", "回到工作台确认 Attempt ID 并提交"],
                        ["申诉按钮不可用", "未选择 criterion、理由少于 3 个字符或没有成绩", "补充理由并选择评分项"],
                        ["提示看起来不相关", "系统可能误判卡住场景", "点击 `这不是卡住` 并继续实践"],
                        ["自动提示打扰操作", "自动提示开启", "点击 `关闭自动提示`"],
                    ],
                ),
            ],
        },
        {
            "title": "本地和 IPv6 访问说明",
            "blocks": [
                block(
                    "p",
                    "本地开发环境常见访问地址是 `http://127.0.0.1:3000`。如果教师给出 IPv6 地址，你可以直接在浏览器打开。页面会尽量把终端 WebSocket 地址改写为当前页面主机，保证远程访问时不会错误连接到你自己电脑的回环地址。",
                ),
                block(
                    "bullets",
                    [
                        "本机访问优先使用 `http://127.0.0.1:3000`。",
                        "同一局域网或校园网访问 IPv6 地址时，应使用教师给出的完整 `http://[ipv6]:3000/` 格式。",
                        "如果页面能打开但终端不能连，可能是 Gateway 端口、防火墙或 IPv6 监听问题。",
                        "如果静态资源加载失败，可能是 Web standalone 静态文件复制不完整，需要教师修复部署。",
                    ],
                ),
            ],
        },
        {
            "title": "学生端操作清单",
            "blocks": [
                block(
                    "checklist",
                    [
                        "确认自己使用的是学生账号或学生 token。",
                        "打开学生工作台并点击 `启动`。",
                        "确认状态为 `connected`，Attempt ID 和 session epoch 已显示。",
                        "在终端中完成题目要求，不攻击平台控制平面。",
                        "卡住时先请求 L1，再根据需要请求 L2 或 L3。",
                        "对不准确提示及时反馈。",
                        "提交前检查答案不包含 token、动态 secret 或内部地址。",
                        "提交后查看成绩摘要和完整证据页。",
                        "如需申诉，选择具体 criterion 并写清事实依据。",
                        "课程结束后清理开发 token，尤其是在共享电脑上。",
                    ],
                ),
            ],
        },
        {
            "title": "学生端功能速查",
            "blocks": [
                block(
                    "table",
                    headers=["你要做什么", "入口", "说明"],
                    rows=[
                        ["开始实验", "工作台 `启动`", "创建 Attempt、LabSession 和终端连接"],
                        ["恢复连接", "工作台 `重连`", "保留当前环境，重新签发票据"],
                        ["清理环境", "工作台 `重置`", "新 session epoch，旧票据失效"],
                        ["输入命令", "中间终端", "浏览器终端连接隔离 workspace"],
                        ["请求提示", "右侧 L1/L2/L3", "分级辅助，不泄露最终 payload"],
                        ["反馈提示", "提示卡片按钮", "`接受`、`稍后`、`这不是卡住`、`关闭自动提示`"],
                        ["提交答案", "右侧提交区", "填写 root-cause 解释并提交"],
                        ["查看简要成绩", "右侧成绩证据", "显示 Total 和各项简要分数"],
                        ["查看完整成绩", "`完整证据页`", "查看每项得分、解释和证据引用"],
                        ["提交申诉", "成绩页右侧申诉面板", "按 criterion 提交具体理由"],
                    ],
                ),
            ],
        },
    ]
    return Manual(
        slug="student-guide",
        title="CyberLab Assistant（CLA）学生端使用手册",
        subtitle="浏览器终端实践、分级提示、答案提交、成绩证据与申诉",
        audience="网安实践课程学生",
        pdf_name="cla-student-guide.pdf",
        sections=sections,
    )


def inline_pdf(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    rendered: list[str] = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            rendered.append(f'<font name="{ACTIVE_PDF_FONT_NAME}">{html.escape(part[1:-1])}</font>')
        else:
            rendered.append(html.escape(part))
    return "".join(rendered)


def render_markdown(manual: Manual) -> str:
    lines = [
        f"# {manual.title}",
        "",
        manual.subtitle,
        "",
        f"- 适用对象：{manual.audience}",
        f"- 生成日期：{GENERATED_AT}",
        "- 项目名称：CyberLab Assistant（CLA）",
        "- 相关规格：`cla_terminal_first_complete_development_spec.html`",
        "",
        "## 目录",
        "",
    ]
    for index, section in enumerate(manual.sections, start=1):
        lines.append(f"{index}. [{section['title']}](#{slug(section['title'])})")
    lines.append("")
    for index, section in enumerate(manual.sections, start=1):
        lines.extend([f'<a id="{slug(section["title"])}"></a>', f"## {index}. {section['title']}", ""])
        for item in section["blocks"]:
            kind = item["kind"]
            if kind == "p":
                lines.extend([item["content"], ""])
            elif kind == "note":
                lines.extend([f"> **{item['title']}**：{item['content']}", ""])
            elif kind in {"bullets", "checklist"}:
                mark = "- [ ]" if kind == "checklist" else "-"
                for text in item["content"]:
                    lines.append(f"{mark} {text}")
                lines.append("")
            elif kind == "steps":
                for step_index, text in enumerate(item["content"], start=1):
                    lines.append(f"{step_index}. {text}")
                lines.append("")
            elif kind == "code":
                lines.extend(["```bash", item["content"].strip("\n"), "```", ""])
            elif kind == "table":
                headers = item["headers"]
                lines.append("| " + " | ".join(headers) + " |")
                lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for row in item["rows"]:
                    lines.append("| " + " | ".join(str(cell).replace("\n", "<br>") for cell in row) + " |")
                lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(manual: Manual) -> str:
    nav = "\n".join(
        f'<a href="#{slug(section["title"])}">{i}. {html.escape(section["title"])}</a>'
        for i, section in enumerate(manual.sections, start=1)
    )
    body_parts: list[str] = []
    for index, section in enumerate(manual.sections, start=1):
        body_parts.append(f'<section id="{slug(section["title"])}"><h2>{index}. {html.escape(section["title"])}</h2>')
        for item in section["blocks"]:
            body_parts.append(render_html_block(item))
        body_parts.append("</section>")
    body = "\n".join(body_parts)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(manual.title)}</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f7f8fb;
  --panel: #ffffff;
  --text: #172033;
  --muted: #637083;
  --line: #d9e0ea;
  --brand: #1957c2;
  --code: #0b1220;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
  line-height: 1.72;
}}
.layout {{
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 100vh;
}}
aside {{
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  background: var(--panel);
  border-right: 1px solid var(--line);
  padding: 22px 18px;
}}
aside h1 {{
  font-size: 17px;
  line-height: 1.35;
  margin: 0 0 8px;
}}
aside p {{
  color: var(--muted);
  font-size: 12px;
  margin: 0 0 18px;
}}
nav a {{
  display: block;
  color: var(--muted);
  text-decoration: none;
  padding: 6px 8px;
  border-radius: 7px;
  font-size: 12px;
}}
nav a:hover {{
  color: var(--brand);
  background: #edf2f8;
}}
main {{
  max-width: 1080px;
  width: 100%;
  margin: 0 auto;
  padding: 42px 34px 80px;
}}
header {{
  border-bottom: 1px solid var(--line);
  margin-bottom: 28px;
  padding-bottom: 22px;
}}
header h1 {{
  font-size: 34px;
  line-height: 1.2;
  margin: 0 0 10px;
}}
header p {{
  color: var(--muted);
  margin: 4px 0;
}}
section {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 22px;
  margin: 18px 0;
}}
h2 {{
  font-size: 22px;
  margin: 0 0 12px;
}}
.note {{
  border-left: 4px solid var(--brand);
  background: #eef4ff;
  padding: 12px 14px;
  margin: 14px 0;
}}
.note strong {{
  display: block;
  margin-bottom: 4px;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  margin: 14px 0;
  font-size: 13px;
}}
th, td {{
  border: 1px solid var(--line);
  padding: 8px 9px;
  vertical-align: top;
}}
th {{
  background: #edf2f8;
}}
code {{
  font-family: "SFMono-Regular", Consolas, monospace;
  color: #102a5c;
}}
pre {{
  background: var(--code);
  color: #edf4ff;
  padding: 14px;
  overflow: auto;
  border-radius: 7px;
  font-size: 12px;
  line-height: 1.55;
}}
pre code {{
  color: inherit;
}}
@media (max-width: 860px) {{
  .layout {{ display: block; }}
  aside {{ position: static; height: auto; }}
  main {{ padding: 24px 16px 60px; }}
}}
@media print {{
  body {{ background: white; }}
  aside {{ display: none; }}
  .layout {{ display: block; }}
  main {{ max-width: none; padding: 0; }}
  section {{ break-inside: avoid; border-color: #ddd; }}
}}
</style>
</head>
<body>
<div class="layout">
<aside>
<h1>{html.escape(manual.title)}</h1>
<p>{html.escape(manual.subtitle)}<br>生成日期：{GENERATED_AT}</p>
<nav>
{nav}
</nav>
</aside>
<main>
<header>
<h1>{html.escape(manual.title)}</h1>
<p>{html.escape(manual.subtitle)}</p>
<p>适用对象：{html.escape(manual.audience)} · 生成日期：{GENERATED_AT}</p>
<p>项目名称：CyberLab Assistant（CLA） · 相关规格：cla_terminal_first_complete_development_spec.html</p>
</header>
{body}
</main>
</div>
</body>
</html>
"""


def render_html_block(item: dict[str, Any]) -> str:
    kind = item["kind"]
    if kind == "p":
        return f"<p>{html.escape(item['content'])}</p>"
    if kind == "note":
        return f"<div class=\"note\"><strong>{html.escape(item['title'])}</strong>{html.escape(item['content'])}</div>"
    if kind in {"bullets", "checklist"}:
        items = "\n".join(f"<li>{html.escape(text)}</li>" for text in item["content"])
        return f"<ul>{items}</ul>"
    if kind == "steps":
        items = "\n".join(f"<li>{html.escape(text)}</li>" for text in item["content"])
        return f"<ol>{items}</ol>"
    if kind == "code":
        return f"<pre><code>{html.escape(item['content'].strip())}</code></pre>"
    if kind == "table":
        headers = "".join(f"<th>{html.escape(str(header))}</th>" for header in item["headers"])
        rows = []
        for row in item["rows"]:
            cells = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
            rows.append(f"<tr>{cells}</tr>")
        return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    raise ValueError(f"unknown block kind: {kind}")


def build_pdf(manual: Manual) -> None:
    register_pdf_font()
    output = PDF_DIR / manual.pdf_name
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=17 * mm,
        title=manual.title,
        author="CyberLab Assistant（CLA）",
    )
    width = A4[0] - doc.leftMargin - doc.rightMargin
    styles = pdf_styles()
    story: list[Any] = [
        Spacer(1, 34 * mm),
        Paragraph(manual.title, styles["cover"]),
        Spacer(1, 8 * mm),
        Paragraph(manual.subtitle, styles["subtitle"]),
        Spacer(1, 8 * mm),
        Paragraph(f"适用对象：{manual.audience}", styles["meta"]),
        Paragraph(f"生成日期：{GENERATED_AT}", styles["meta"]),
        Paragraph("项目名称：CyberLab Assistant（CLA）", styles["meta"]),
        Paragraph("相关规格：cla_terminal_first_complete_development_spec.html", styles["meta"]),
        PageBreak(),
        Paragraph("目录", styles["h1"]),
    ]
    for index, section in enumerate(manual.sections, start=1):
        story.append(Paragraph(f"{index}. {inline_pdf(section['title'])}", styles["toc"]))
    story.append(PageBreak())

    for index, section in enumerate(manual.sections, start=1):
        story.append(Paragraph(f"{index}. {inline_pdf(section['title'])}", styles["h1"]))
        story.append(Spacer(1, 3 * mm))
        for item in section["blocks"]:
            add_pdf_block(story, item, styles, width)
        story.append(Spacer(1, 5 * mm))

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = ACTIVE_PDF_FONT_NAME
    return {
        "cover": ParagraphStyle(
            "cover",
            fontName=base,
            fontSize=22,
            leading=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#172033"),
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=base,
            fontSize=13,
            leading=20,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#4c5b70"),
        ),
        "meta": ParagraphStyle(
            "meta",
            fontName=base,
            fontSize=10,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#637083"),
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName=base,
            fontSize=16,
            leading=22,
            textColor=colors.HexColor("#123f8f"),
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=base,
            fontSize=9.4,
            leading=14.2,
            textColor=colors.HexColor("#172033"),
            spaceAfter=5,
        ),
        "note": ParagraphStyle(
            "note",
            fontName=base,
            fontSize=9.2,
            leading=14,
            textColor=colors.HexColor("#172033"),
            leftIndent=8,
            rightIndent=8,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "toc": ParagraphStyle(
            "toc",
            fontName=base,
            fontSize=10.5,
            leading=16,
            textColor=colors.HexColor("#172033"),
        ),
        "table": ParagraphStyle(
            "table",
            fontName=base,
            fontSize=8.0,
            leading=11,
            textColor=colors.HexColor("#172033"),
        ),
        "code": ParagraphStyle(
            "code",
            fontName=base,
            fontSize=7.2,
            leading=9.2,
            textColor=colors.HexColor("#0b1220"),
            leftIndent=4,
            rightIndent=4,
        ),
    }


def add_pdf_block(story: list[Any], item: dict[str, Any], styles: dict[str, ParagraphStyle], width: float) -> None:
    kind = item["kind"]
    if kind == "p":
        story.append(Paragraph(inline_pdf(item["content"]), styles["body"]))
    elif kind == "note":
        text = f"<b>{inline_pdf(item['title'])}</b>：{inline_pdf(item['content'])}"
        table = Table([[Paragraph(text, styles["note"])]], colWidths=[width])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef4ff")),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#1957c2")),
                    ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e0ea")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 3 * mm))
    elif kind in {"bullets", "checklist"}:
        for text in item["content"]:
            prefix = "□" if kind == "checklist" else "•"
            story.append(Paragraph(f"{prefix} {inline_pdf(text)}", styles["body"]))
        story.append(Spacer(1, 2 * mm))
    elif kind == "steps":
        for index, text in enumerate(item["content"], start=1):
            story.append(Paragraph(f"{index}. {inline_pdf(text)}", styles["body"]))
        story.append(Spacer(1, 2 * mm))
    elif kind == "code":
        wrapped = wrap_code(item["content"])
        story.append(Preformatted(wrapped, styles["code"], maxLineLength=96))
        story.append(Spacer(1, 3 * mm))
    elif kind == "table":
        rows = [[Paragraph(inline_pdf(str(cell)), styles["table"]) for cell in item["headers"]]]
        for row in item["rows"]:
            rows.append([Paragraph(inline_pdf(str(cell)), styles["table"]) for cell in row])
        col_count = len(item["headers"])
        col_widths = [width / col_count] * col_count
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f8")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#172033")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e0ea")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 4 * mm))
    else:
        raise ValueError(f"unknown block kind: {kind}")


def draw_footer(canvas: Any, doc: SimpleDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont(ACTIVE_PDF_FONT_NAME, 8)
    canvas.setFillColor(colors.HexColor("#637083"))
    canvas.drawString(18 * mm, 9 * mm, "CyberLab Assistant（CLA）使用手册")
    canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def wrap_code(code: str) -> str:
    output: list[str] = []
    for line in code.strip("\n").splitlines():
        if not line:
            output.append("")
            continue
        parts = textwrap.wrap(
            line,
            width=92,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        )
        output.extend(parts or [""])
    return "\n".join(output)


def register_pdf_font() -> None:
    global ACTIVE_PDF_FONT_NAME
    if ACTIVE_PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    for candidate in PDF_FONT_CANDIDATES:
        if candidate.exists() and candidate.suffix.lower() == ".ttf":
            pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(candidate)))
            ACTIVE_PDF_FONT_NAME = PDF_FONT_NAME
            return
    pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT_FALLBACK))
    ACTIVE_PDF_FONT_NAME = PDF_FONT_FALLBACK


def slug(value: str) -> str:
    normalized = re.sub(r"\s+", "-", value.strip().lower())
    normalized = re.sub(r"[^\w\-\u4e00-\u9fff]", "", normalized)
    return normalized


def write_manual(manual: Manual) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    (DOC_DIR / f"{manual.slug}.md").write_text(render_markdown(manual), encoding="utf-8")
    (DOC_DIR / f"{manual.slug}.html").write_text(render_html(manual), encoding="utf-8")
    build_pdf(manual)


def main() -> None:
    for manual in (teacher_manual(), student_manual()):
        write_manual(manual)
        print(f"generated {manual.slug}: docs/user-manuals/{manual.slug}.md, docs/user-manuals/{manual.slug}.html, output/pdf/{manual.pdf_name}")


if __name__ == "__main__":
    main()
