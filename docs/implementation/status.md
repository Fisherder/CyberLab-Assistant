# 实施状态

需求基线：[cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html)。

## 本轮完成

- 已按用户视角重写教师端和学生端使用手册：从进入页面、点击按钮、输入内容、查看结果到常见问题逐步说明，不再把开发接口、内部模块和实现细节作为主体内容。
- 已新增本地账号注册登录功能：学生和教师可以通过 `/login` 页面注册或登录，登录后获得平台会话 token；学生进入终端工作台，教师进入验证报告页，退出登录会清除浏览器 token。
- 已在后端新增本地账号密码哈希、会话 token、注册/登录接口和 Alembic 迁移，并保留原有 OIDC、开发 token、RBAC、课程成员权限检查。
- 已为手册补充真实本机页面截图，覆盖学生工作台、终端连接、提示、答案提交、成绩证据、申诉，以及教师验证报告和实时监控页面。
- 已更新 `tools/build_user_manuals.py`，用同一份结构化内容生成 Markdown、HTML 和 PDF，便于后续同步维护教师端和学生端手册。
- 当前用户手册源文档位于 `docs/user-manuals/teacher-guide.md`、`docs/user-manuals/student-guide.md`，HTML 版本位于 `docs/user-manuals/teacher-guide.html`、`docs/user-manuals/student-guide.html`，PDF 版本位于 `output/pdf/cla-teacher-guide.pdf` 和 `output/pdf/cla-student-guide.pdf`。
- 已把用户使用手册入口加入根目录 `README.md` 的阅读顺序和仓库结构说明。
- 已将 PDF 生成改为嵌入本机中文字体，避免 Poppler 缺少 Adobe-GB1 映射时出现中文渲染失败。
- 已抽样渲染教师端 PDF 第 4、8 页和学生端 PDF 第 5、10、12、13 页，确认截图、正文、表格、清单和页脚可读且没有明显溢出。
- 已重写根目录 `README.md`，作为人类开发人员和后续 agent 的中文入口文档，覆盖项目定位、当前实现边界、模块职责、核心链路、本地运行、测试、文档维护、Git 和后续路线。
- 已新增 `docs/development/developer-guide.md`、`docs/development/architecture.md`、`docs/development/security.md`、`docs/development/testing.md`、`docs/development/git.md` 和 `docs/development/content-authoring.md`，分别覆盖开发规范、架构、不可突破安全边界、测试矩阵、Git 协作和 Challenge-as-Code 内容规范。
- 已扩展 `docs/runbooks/local-development.md`，补齐本地 API、Gateway、sessiond、Web、Compose、手动纵向验证和排障步骤。
- 已新增 `.gitignore`，避免提交 `.venv`、`node_modules`、`.next`、`__pycache__`、本地数据库、密钥和运行缓存。
- 已迁移隐藏配置文件：`.env.example`、`.dockerignore` 和 `.github/workflows/ci.yml` 均改为 CLA 环境变量、PostgreSQL 用户、pnpm 包名和忽略项。
- 已将 `Taskfile.yml` 的任务说明改为中文，并将规格 HTML 的左侧 logo 从旧品牌暗示改为 CLA 对应标识。
- 项目命名已从旧缩写整体迁移为 CyberLab Assistant（CLA）：Python 包路径、Go module、环境变量、Header、Prometheus 指标命名空间、Helm/Compose、OpenAPI/Protobuf 文件名、shell hook、规格文件名、测试断言和文档链接均已更新为 `cla/CLA`。
- API 包从 `services/api/src/cla` 启动，Docker CMD 使用 `cla.main:app`。
- Go module 从 `cla-platform` 与 `cla.local/sessionwire` 解析。
- Helm chart 目录改为 `deploy/helm/cla`，镜像名、ServiceAccount、Secret 和内部 URL 改为 `cla-*`。
- 环境变量统一使用 `CLA_` 前缀，内部服务 Header 使用 `X-CLA-Service-Token`，Oracle 签名 Header 使用 `X-CLA-Oracle-Signature`。
- 项目文档、ADR 和运行手册已改为中文说明，面向中文开发人员和专家阅读。
- S3 transcript 不只保留 helper 级测试，已新增内部 API 级测试，覆盖 `/upload`、`/verify-restore` 和 `/apply-retention` 在 fake S3 后端下的写入、恢复和保留清理。
- 已启动本机实例并完成浏览器纵向验证：学生工作台创建 Attempt、创建 LabSession、签发终端票据、Gateway 连接 sessiond、执行终端命令、请求 L1 提示、提交答案、查看成绩证据、提交申诉、教师 API 复核生成新 GradeRevision、教师验证报告页和 live monitor 页渲染正常。
- 已修复旧版 SQLite 开发库 `appeals` 表缺少 `criterion_id` 导致申诉 500 的问题，启动时仅对 SQLite 本地库做缺列兼容，并增加回归测试。
- 已为本地 Web 验证增加 `#claDevToken=` URL hash 写入方式，便于浏览器自动化和人工验证；页面读取后会清理地址栏中的 token。
- 已让前端在通过 IPv6 页面访问时，把 API 返回的本地回环 Gateway WebSocket 地址改写为当前页面主机，避免 IPv6 页面连接到访问者本机的 `127.0.0.1`。

## 当前已验证能力

- API 控制平面：OIDC、RBAC、课程/成员/作业、Attempt 幂等、LabSession、本地 reset、终端票据、路由注册、票据撤销、事件接入、转录索引/加密/恢复/保留、Oracle、评分、申诉、Tutor、教师监控和内容验证。
- 本地账号认证：注册学生账号、学生登录、创建 Attempt，注册教师账号、教师访问验证报告和 live monitor 均已通过 API 测试和本机浏览器验证。
- Gateway/sessiond：二进制 STDIN/STDOUT、resize、heartbeat、ACK、重连 replay、Redis replay、背压、异步录制和 metrics。
- Environment Controller：LabSession CRD 类型、资源规划、调和决策、controller-runtime fake client、Kubernetes Event、route registry、ticket revoke、orphan scanner 和 metrics。
- Web：学生工作台、成绩证据页、教师验证报告页、教师 live monitor 页面可以构建并通过类型检查；本机浏览器已验证学生终端连接、命令回显、提示、提交、成绩页、申诉、教师验证报告和教师 live monitor。
- 一期 GUI 预留：REMOTE_DESKTOP 与 SIMULATED 只保留类型和 Feature Flag，不进入运行依赖。

## 本轮实际运行命令与结果

```bash
.venv/bin/python -m pytest services/api/tests
# 结果：65 passed, 1 skipped in 3.86s，包含本地账号注册登录测试

env GOCACHE=/private/tmp/cla-go-cache /tmp/cla-go/go/bin/go test ./packages/sessionwire/... ./services/terminal-gateway/... ./services/environment-controller/... ./runtime/sessiond/...
# packages/sessionwire：通过
# services/terminal-gateway：通过
# runtime/sessiond：通过
# services/environment-controller：通过

.venv/bin/python -m compileall services/api/src services/api/tests services/agent-runtime/src workers/temporal/src content/challenges/web-sqli-auth
# 结果：Python 编译检查通过

env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web build
# 结果：Next.js build 通过

env CI=true /Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm --dir apps/web typecheck
# 结果：tsc --noEmit 通过

PYTHONPATH=services/api/src .venv/bin/python -m cla.content_validation --output content/validation/web-sqli-auth-001-1.3.0.validation.json
# 结果：{"passed": 8, "warnings": 1, "blocked": 0}

docker compose -f deploy/compose/docker-compose.yml config
# 结果：Compose 配置解析通过，服务环境变量使用 CLA_ 前缀

curl --noproxy '*' -sS http://127.0.0.1:8000/healthz
# 结果：{"ok":true,"agentRuntimeEnabled":false}

curl --noproxy '*' -sS http://127.0.0.1:8081/healthz
# 结果：ok

curl --noproxy '*' -g -6 -I --max-time 5 'http://[2001:da8:215:8f02:8b9:8bea:15bd:6c74]:3000/'
# 结果：HTTP/1.1 200 OK

docker info
# 结果：Docker 客户端存在，但 OrbStack daemon socket 不存在，无法执行 live Compose。

kubectl cluster-info
# 结果：localhost:8080 refused，当前没有可用 Kubernetes 集群。

legacy_lower='z''y''a'
legacy_upper='Z''Y''A'
legacy_title='Z''y''a'
rg --hidden -n "${legacy_upper}|${legacy_lower}|${legacy_title}" . --glob '!.git/**' --glob '!node_modules/**' --glob '!apps/web/node_modules/**' --glob '!.pnpm-store/**' --glob '!apps/web/.next/**' --glob '!**/__pycache__/**' --glob '!*.pyc' --glob '!*.db'
# 结果：无匹配

find . -path './.git' -prune -o -path './node_modules' -prune -o -path './apps/web/node_modules' -prune -o -path './.pnpm-store' -prune -o -path './apps/web/.next' -prune -o -iname "*${legacy_lower}*" -print
# 结果：无匹配

/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 tools/build_user_manuals.py
# 结果：生成教师端和学生端 Markdown、HTML、PDF 手册

/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pdfinfo output/pdf/cla-teacher-guide.pdf
# 结果：8 pages，A4，未加密，无 JavaScript

/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pdfinfo output/pdf/cla-student-guide.pdf
# 结果：13 pages，A4，未加密，无 JavaScript

/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pdftoppm -f 8 -l 8 -png output/pdf/cla-teacher-guide.pdf tmp/pdfs/rendered/user-teacher-08-final2
/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pdftoppm -f 12 -l 12 -png output/pdf/cla-student-guide.pdf tmp/pdfs/rendered/user-student-12-final2
/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pdftoppm -f 13 -l 13 -png output/pdf/cla-student-guide.pdf tmp/pdfs/rendered/user-student-13-final
# 结果：抽样 PNG 渲染成功，目视检查截图、正文、表格、清单和页脚可读
```

说明：`next build` 会重写 `apps/web/next-env.d.ts` 的生成注释，本轮构建和类型检查通过后已再次把该文件注释修正为中文，并单独重跑 typecheck 通过。Go 根目录 `./...` 不适用于当前 go.work 布局，因此状态文档和开发文档均使用明确模块路径集合。

## 当前可演示路径

1. 教师/学生可通过开发 token 调用 API。
2. 教师可创建课程、成员和作业。
3. 学生可幂等创建 Attempt，创建本地 LabSession，并获取 60 秒一次性终端票据。
4. Gateway 通过内部 consume API 获得 nested `sessionRoute`，前端不会获得 route/endpoint/sessiond 地址。
5. Shell hook/Gateway 可以写入语义事件和加密终端分片索引。
6. Oracle 签名观测可以发布客观证据，提交后生成 GradeRevision 和 CriterionResult。
7. 学生可查看证据化成绩并提交 criterion 级申诉。
8. 教师可查看验证报告和 live monitor，并可通过复核 API 处理申诉，生成新的不可变 GradeRevision。
9. 本机浏览器已验证 xterm.js 到 Gateway/sessiond 的真实 PTY 链路，命令 `echo CLA_DEFAULT_TOKEN_OK` 正常回显，内部票据消费返回 200，终端分片上传返回 202。

## 已知限制

- Docker daemon 当前不可用，因此真实 `docker compose build/up`、Compose Postgres/Redis/MinIO/target live smoke 未运行。
- Kubernetes controller 目前通过 fake client、静态 Helm/CRD 和单元测试验证；当前没有可用 Kubernetes 集群，真实集群 apply、NetworkPolicy、gVisor/Kata、节点故障和 orphan cleanup 未运行。
- Temporal Worker 仍是边界包，P1 使用同步确定性替代路径。
- live MinIO/S3 对象生命周期、bucket policy、恢复演练和理由审计访问控制未完成。
- PostgreSQL 迁移 smoke 已接入 `CLA_TEST_POSTGRES_URL`，但本地没有可用 PostgreSQL URL。
- Tutor 模型边界案例、precision/recall 标定、负载测试、混沌测试和完整安全攻防测试未完成。
- 教师评分复核 UI、管理员策略 UI、课程管理完整 UI 仍未实现。
- 浏览器纵向验证已覆盖终端、提示、提交、成绩、申诉和教师监控；仍未完成真实 target/Oracle PASS 的 Compose live 版本，因为 Docker daemon 不可用。

## 下一步

1. 在可用 Docker daemon 上运行 `docker compose -f deploy/compose/docker-compose.yml build` 与 `up` smoke。
2. 在 Docker daemon 可用后补跑真实 target/Oracle PASS 浏览器 E2E：登录、Attempt、Lab Ready、xterm.js 连接、curl、Oracle PASS、提交、成绩页和申诉。
3. 对 live MinIO/S3 执行 transcript 上传、恢复、保留删除和恢复演练。
4. 在开发 Kubernetes 集群 apply CRD/Helm，验证真实 controller route registry、NetworkPolicy、gVisor/Kata 和 orphan cleanup。
5. 将本地同步 session lifecycle 和 grading orchestration 迁入 Temporal。
6. 补齐生产观测 Dashboard、告警、容量、混沌和安全测试。
