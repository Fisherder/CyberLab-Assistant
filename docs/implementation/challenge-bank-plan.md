# 题库功能技术实现路线

需求来源：[题库要求.md](/Users/fisherder/Desktop/研究生/Security_Class_Tool/题库要求.md)。
系统总基线：[cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html)。

## 术语边界

### 题目数据库

题目数据库是内容资产层，当前由 `challenges`、`challenge_versions`、`challenge_artifacts`、`validation_runs` 和 Challenge Registry 接口组成。

它负责：

- 保存 Challenge-as-Code 题目包和不可变版本。
- 记录题目包对象资产、验证报告、模型生成草稿。
- 给教师出题 Agent 提供检索候选。
- 保证版本发布前经过验证和审批。

题目数据库不直接决定学生能不能看到题目，也不直接代表一次课堂活动。

### 题库

题库是教学发布层，是教师面向某门课程创建和管理的题目列表。它引用题目数据库中的一个已验证题目版本，并额外管理：

- 题库条目标题、描述、要求、标签和发布说明。
- 未发布、已发布、未开始、进行中、已结束、已下架、已删除等状态。
- 开始时间和截止时间。
- 教师增删改查、下架、恢复、回收站。
- 学生端可见题目列表和获取实验环境入口。

题库条目可以修改，但修改已发布题目必须先下架。下架后保留原发布时间字段，教师修改后可以再次发布。

## 本轮目标

本轮实现可运行的本地纵向切片：

1. 新增题库条目数据模型 `challenge_bank_items`。
2. 教师 API 支持创建、列表、详情、修改、发布、下架、删除、回收站和恢复。
3. 学生 API 支持查看已发布题库；未开始和已结束题目灰显但可预览；只有进行中题目能开启环境。
4. 学生获取容器时复用现有 Assignment、Attempt、LabSession、Gateway 链路，确保同一学生同一题目只创建一个 Attempt，但不同题目可以各自创建 Attempt。
5. 前端增加教师题库页面和学生题库页面，教师端不再把学生做题界面作为主要入口。
6. 文档和测试覆盖生命周期、权限、时间窗口、删除/恢复和 Attempt 幂等约束。

## 数据模型

新增表：`challenge_bank_items`。

字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 题库条目 ID |
| `tenant_id` | 租户 |
| `course_id` | 所属课程 |
| `challenge_version_id` | 引用的题目数据库版本 |
| `assignment_id` | 对应现有作业，发布时自动创建或复用 |
| `title` | 教师端和学生端显示标题 |
| `summary` | 题目摘要 |
| `description` | 题目详情 |
| `requirements` | 学生提交和操作要求 |
| `status` | `DRAFT`、`PUBLISHED`、`UNPUBLISHED`、`DELETED` |
| `publish_state` | 计算态：`UNPUBLISHED`、`NOT_STARTED`、`ACTIVE`、`ENDED`、`DELETED` |
| `open_at` | 开始时间，发布时必填 |
| `due_at` | 截止时间，发布时必填 |
| `tags_json` | 标签 |
| `created_by` | 创建教师 |
| `created_at` / `updated_at` | 创建和更新时间 |
| `published_at` | 最近发布时间 |
| `unpublished_at` | 最近下架时间 |
| `deleted_at` | 删除时间，用于最近 30 条回收站 |
| `restored_at` | 最近恢复时间 |

约束：

- `assignment_id` 唯一，避免一个题库条目映射多个课堂作业。
- 教师端只能操作本课程题库。
- 学生端只能读取自己课程内未删除且已发布过的题库条目。
- 已发布题目不能直接修改或删除，必须先下架。

## API 设计

教师端：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/teacher/challenge-bank` | 教师题库列表，包含未发布、未开始、进行中、已结束和已下架 |
| `POST` | `/api/v1/teacher/challenge-bank` | 从题目数据库版本创建题库条目，可选择同时发布 |
| `GET` | `/api/v1/teacher/challenge-bank/{item_id}` | 题库条目详情 |
| `PATCH` | `/api/v1/teacher/challenge-bank/{item_id}` | 修改未发布/已下架题目 |
| `POST` | `/api/v1/teacher/challenge-bank/{item_id}/publish` | 设置开始/截止时间并发布 |
| `POST` | `/api/v1/teacher/challenge-bank/{item_id}/unpublish` | 下架题目，保留发布时间字段 |
| `DELETE` | `/api/v1/teacher/challenge-bank/{item_id}` | 删除未发布/已下架题目 |
| `GET` | `/api/v1/teacher/challenge-bank/trash` | 最近 30 条已删除题目 |
| `POST` | `/api/v1/teacher/challenge-bank/{item_id}/restore` | 从回收站恢复为未发布 |

学生端：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/student/challenge-bank` | 学生题库列表，只显示已发布题目，按时间计算可点击状态 |
| `GET` | `/api/v1/student/challenge-bank/{item_id}` | 学生题目详情 |
| `POST` | `/api/v1/student/challenge-bank/{item_id}/start` | 获取或创建本人该题目的 Attempt 和 LabSession |

## 学生环境与目标地址

本轮本地切片复用现有 LabSession：

1. 题库条目发布时自动创建或复用一个内部 `Assignment`。
2. 学生点击获取容器时按 `assignment_id + student_id` 查找已有 Attempt。
3. 如已有 Attempt，直接返回原 Attempt 和已有 LabSession；如没有则创建 Attempt。
4. `POST /start` 返回：
   - `attemptId`
   - `sessionId`
   - `targetUrl`
   - `terminalUrl`
   - `workspaceUrl`

本地 target 地址使用 manifest 中的 `target.baseUrl`，开发默认是 `http://127.0.0.1:18080`。生产形态需要由环境控制器给每个 Attempt 生成可从学生浏览器访问的临时外部地址，不能暴露 Pod IP 或 sessiond 地址。

## 辅助 Agent 与外部访问观测

题库要求中“学生用浏览器、Postman 或本机工具访问目标也要被监测”不能只靠终端 shell hook。设计路线：

1. 在每个 target 前放置 per-attempt HTTP 观测代理或入口网关。
2. 学生拿到的 `targetUrl` 指向该观测入口，而不是容器内服务地址。
3. 入口记录请求摘要、响应状态、路径、方法、时间、attempt_id、session_epoch，并写入统一事件流。
4. 敏感 header、Cookie、Authorization 和请求体默认不进入普通日志；只保留规则允许的摘要和证据引用。
5. Tutor 使用终端事件、HTTP 交互摘要、Oracle 事件和提交内容做 StuckAssessment。

本轮实现接口和事件字段预留，并在本地 targetUrl 返回控制平面可访问地址；完整 per-attempt HTTP 观测代理放入后续 K8s/Env Controller 里实现。

## 前端路线

教师端 `/teacher/challenge-bank`：

- 默认页面是题库列表，不是做题界面。
- 顶部按钮：创建题目、导入题目数据库、回收站。
- 列表卡片显示标题、状态、开始时间、截止时间、引用版本、标签。
- 详情区显示题目描述、要求、引用版本、验证状态和操作按钮。
- 未发布/已下架：可修改、发布、删除。
- 已发布/未开始/进行中/已结束：只能查看和下架。
- 回收站：只显示最近 30 条删除项，可恢复。

学生端 `/student/challenge-bank`：

- 展示已发布题目列表。
- 未开始和已结束卡片灰显，不允许开启环境。
- 进行中卡片可打开详情并点击获取容器。
- 获取容器后展示目标地址和进入终端按钮。

## 验收清单

- 教师能从已发布 ChallengeVersion 创建题库条目。
- 创建时可以仅创建不发布，也可以带开始/截止时间直接发布。
- 发布必须有开始时间和截止时间，且截止时间晚于开始时间。
- 已发布题目不能直接修改或删除；下架后可以修改或删除。
- 删除后不出现在教师普通题库和学生题库中；回收站显示最近 30 条。
- 恢复后状态为未发布，重新出现在教师题库。
- 学生只看到已发布题目；未开始/已结束不可点击开启环境。
- 同一学生同一题目重复点击获取容器返回同一 Attempt。
- 同一学生不同题目可以分别获取不同 Attempt。
- 学生响应不暴露 Pod、容器 IP、sessiond 地址或内部 route_ref。
- API、Web build/typecheck 和相关测试通过。
