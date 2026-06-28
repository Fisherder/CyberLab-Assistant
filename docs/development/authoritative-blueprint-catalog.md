# 权威题型蓝图库开发说明

本文说明 CLA 当前的大规模题目数据库、检索组合和无匹配定制生成流程。需求基线仍以 [cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html) 为准，尤其是 P3 Content & Authoring 中关于 Challenge Registry、硬约束过滤、候选解释、教师审核和 Agent 能力边界的要求。

## 目标

权威题型蓝图库用于解决两个问题：

1. 教师给出 Brief 时，系统优先从现有题型和完整题目中检索候选，并尽量通过多个题型蓝图组合出符合教学目标的复合题。
2. 当硬约束过滤后没有候选时，系统生成一个可审核的定制靶场代码包草稿，由教师和内容 CI 继续验证、修改和发布。

蓝图不是直接给学生使用的题面，也不是外部平台题目的镜像。它记录的是题型、知识点、组件、组合关系和生成模板参数。

## 数据文件

核心文件：

- [tools/generate_authoritative_blueprint_catalog.py](/Users/fisherder/Desktop/研究生/Security_Class_Tool/tools/generate_authoritative_blueprint_catalog.py)：生成脚本。
- [content/challenge-blueprints/authoritative-catalog.yaml](/Users/fisherder/Desktop/研究生/Security_Class_Tool/content/challenge-blueprints/authoritative-catalog.yaml)：生成后的蓝图库。
- [content/validation/authoritative-blueprint.validation.json](/Users/fisherder/Desktop/研究生/Security_Class_Tool/content/validation/authoritative-blueprint.validation.json)：蓝图导入后的验证报告。
- [services/api/src/cla/challenge_catalog.py](/Users/fisherder/Desktop/研究生/Security_Class_Tool/services/api/src/cla/challenge_catalog.py)：导入、验证、组合计划和定制靶场生成逻辑。

当前生成规模：

| 领域 | 蓝图数量 | 主要覆盖 |
|---|---:|---|
| Web 安全 | 50 | SQL 注入、XSS、认证、访问控制、SSRF、文件上传/路径遍历、SSTI/反序列化、XXE、竞态/缓存、API 安全 |
| 逆向工程 | 50 | 字符串恢复、keygen、反调试、壳与自解密、控制流混淆、VM、密码误用、移动端逆向、静态链接逆向、嵌入式逆向 |
| Pwn | 50 | 栈溢出、ROP/ret2libc、格式化字符串、堆利用、UAF、整数错误、shellcode/seccomp、PIE/Canary/NX、沙箱/文件能力、内核风格用户态模型 |

## 来源策略

蓝图库参考公开、常见、教学或训练价值较高的平台主题体系，包括：

- PortSwigger Web Security Academy：Web 漏洞主题和实验分类。
- OWASP WebGoat：Web 应用安全教学目标和课程式漏洞覆盖。
- picoCTF / picoGym：CTF 实践分类覆盖方向。
- pwn.college：二进制利用与逆向模块化训练方向。
- ROP Emporium：ROP 技术阶梯。
- Microcorruption：嵌入式/微控制器逆向训练方向。
- crackmes.one：crackme 题型和难度覆盖方向。
- OverTheWire Wargames：Web、逆向、二进制利用等 wargame 训练类别。
- pwnable.kr：二进制利用、逆向、系统知识等训练主题。

合规边界：

- 不复制外部题面原文。
- 不复制附件、二进制、flag、密码、payload、writeup 或教师解法。
- 不把外部平台资源作为 CLA 直接运行资产。
- 只保留知识点分类、题型抽象、组合关系和生成模板参数。

## 导入流程

教师端按钮“导入权威蓝图”调用：

```text
POST /api/v1/challenge-registry/import-blueprints
```

后端流程：

1. 读取 `content/challenge-blueprints/authoritative-catalog.yaml`。
2. 校验总数、每类最小数量、重复 ID、sourceRefs、generator.template 和 workspaceType。
3. 为每个蓝图创建稳定 ID 的 `Challenge`、`ChallengeVersion`、`ValidationRun` 和 `ChallengeArtifact`。
4. `ChallengeVersion.status` 写为 `BLUEPRINT`，表示它是可检索、可组合、可物化的题型蓝图，不是直接发布给学生的完整题。
5. `ValidationRun.status` 写为 `BLUEPRINT`，报告引用 `content/validation/authoritative-blueprint.validation.json`。

接口返回 `summary.counts`，当前应为：

```json
{"WEB": 50, "REVERSE": 50, "PWN": 50}
```

## 检索与组合

候选接口：

```text
GET /api/v1/challenge-drafts/{draft_id}/candidates
```

检索步骤：

1. `parse_course_intent` 或模型解析得到 `category`、`target`、`difficulty`、`expectedMinutes`、`workspaceType`、`isolationTier`、`allowedTools` 和 `learningObjectives`。
2. 按类别、工作区、隔离等级、难度、预计时间、网络策略和工具能力做硬约束过滤。
3. 对 Brief、类别、目标、学习目标、工具、蓝图标签、archetype、variant 和 vulnerability 做 BM25 风格全文打分。
4. 返回候选的 `matchReasons`、`conflicts`、`searchScore` 和 `retrievalSignals`。
5. `compositionPlan` 会根据 `composition.group` 和 `compatibleGroups` 选择单个最佳候选或多个可组合候选。

组合计划不直接创建学生可见题目。它只给教师一个可审核方案，后续仍要走物化、验证、审批发布。

## 无候选定制生成

当候选为空时，组合计划返回：

```json
{
  "mode": "custom-agent-scaffold",
  "candidateIds": ["custom-agent-scaffold"]
}
```

教师端按钮“生成定制靶场草稿”调用：

```text
POST /api/v1/challenge-drafts/{draft_id}/generate-custom-package
```

后端会生成一个 tar 包资产，并创建 `PENDING_APPROVAL` 的 ChallengeVersion。生成文件包括：

- `manifest.yaml`
- `README.md`
- `rubric.yaml`
- `topology.yaml`
- `workspace/Dockerfile`
- `oracle/validator.py`
- Web 类：`target/Dockerfile`、`target/server.py`
- 逆向类：`target/Dockerfile`、`target/challenge.c`
- Pwn 类：`target/Dockerfile`、`target/vuln.c`

安全边界：

- Agent 或生成逻辑只能产出草稿资产。
- 不能直接部署。
- 不能直接发布。
- 不能绕过验证报告。
- 不能写入动态秘密、真实 token、Cookie、Authorization、教师解法或最终 payload。

## 当前验证命令

```bash
.venv/bin/python tools/generate_authoritative_blueprint_catalog.py
# 期望：count=150，WEB/REVERSE/PWN 各 50

.venv/bin/pytest services/api/tests/test_authoring.py -q
# 覆盖导入 300 条、蓝图验证报告、检索组合、60 场景常见题型矩阵、无候选定制生成和 tar 包内容

/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
# 覆盖教师端 Registry 页面新增入口和类型契约
```

## 后续扩展规范

新增领域或题型时，应优先修改生成脚本，而不是手工编辑 YAML：

1. 在 `SOURCES` 中加入权威来源，只能写公开主页或官方文档 URL。
2. 为领域新增 archetype 和 variants，保持每个常见领域不少于 50 条。
3. 为每个 archetype 写清楚工具能力、组件、组合关系和安全约束。
4. 运行生成脚本和 `test_authoring.py`。
5. 如新增完整 Challenge 包，再走 `import-local` 和内容验证。

如果后续接入 pgvector 或 OpenSearch，必须保持当前 `content.search` 抽象和响应字段兼容；向量分数只能作为排序信号，不能绕过硬约束过滤。
