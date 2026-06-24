# CLA Git 与协作规范

本文说明 CyberLab Assistant（CLA）的本地 Git 初始化、提交范围、分支命名、提交信息、远程推送和发布协作规范。

## 基本原则

- 提交必须可解释、可回滚、可测试。
- 不提交本地环境、缓存、依赖目录、生成数据库、密钥和运行产物。
- 文档、测试和追踪矩阵应与代码变更同提交。
- 安全边界、数据库迁移、契约变更和部署变更要有明确说明。
- 没有测试证据的能力不能在提交说明中写成完成。

## 忽略文件

根目录 `.gitignore` 已忽略：

- Python 虚拟环境、缓存和测试产物。
- Node 依赖、Next.js 构建输出和 TypeScript 构建缓存。
- 本地 SQLite 数据库。
- 临时目录、日志和覆盖率。
- 常见密钥、证书和 kubeconfig。
- macOS `.DS_Store`。

首次 `git add .` 前必须检查：

```bash
git status --short
git check-ignore -v cla-dev.db
git check-ignore -v apps/web/.next
git check-ignore -v services/api/src/cla/__pycache__
```

若 `git check-ignore` 没有命中，应先修正 `.gitignore`。

## 本地初始化

如果目录还不是 Git 仓库：

```bash
git init
git branch -M main
```

初始化后检查状态：

```bash
git status --short
```

第一次提交建议使用：

```bash
git add .
git status --short
git commit -m "docs: 完善 CLA 开发文档和项目规范"
```

## 提交信息

推荐格式：

```text
<type>: <中文摘要>
```

常用类型：

| 类型 | 使用场景 |
|---|---|
| `feat` | 新能力或新接口 |
| `fix` | 修复缺陷或安全问题 |
| `docs` | 文档、ADR、运行手册 |
| `test` | 测试新增或修复 |
| `refactor` | 不改变行为的结构调整 |
| `chore` | 构建、依赖、工具、仓库维护 |
| `security` | 安全边界、权限、密钥、隔离相关修改 |

示例：

```bash
git commit -m "security: 加强终端票据重放拒绝测试"
git commit -m "feat: 增加教师申诉复核接口"
git commit -m "docs: 补充本地 Kubernetes 验证手册"
```

## 分支规范

推荐分支：

| 分支 | 用途 |
|---|---|
| `main` | 可运行主线，所有合并应通过测试 |
| `feat/<topic>` | 新功能 |
| `fix/<topic>` | 缺陷修复 |
| `docs/<topic>` | 文档修改 |
| `security/<topic>` | 安全边界修改 |

主题名建议使用小写英文和短横线，例如：

```text
feat/terminal-reconnect-e2e
security/oracle-signature-hardening
docs/developer-guide
```

## 远程仓库

远程 push 需要一个明确的远程 URL 和权限。常见 URL 形式：

```text
git@github.com:<owner>/<repo>.git
https://github.com/<owner>/<repo>.git
```

设置远程：

```bash
git remote add origin <REMOTE_URL>
git remote -v
```

推送主分支：

```bash
git push -u origin main
```

如果远程已经存在：

```bash
git remote set-url origin <REMOTE_URL>
git push -u origin main
```

推送前必须确认不会泄露：

- `.env` 和 `.env.*`。
- 数据库文件。
- pycache、`.next`、`node_modules`。
- 证书、私钥、kubeconfig。
- 本地对象存储和终端录制明文。

## Pull Request 要求

PR 描述应包含：

- 需求背景和需求编号。
- 主要改动文件。
- 数据库迁移和契约变更。
- 安全影响。
- 测试命令和结果。
- 未验证项和风险。

示例：

```markdown
## 背景
实现 FR-TERM-002 的重连 replay 负例。

## 改动
- Gateway replay gap 返回稳定错误码。
- Web 收到 fullRefreshRequired 后进入错误态。
- 增加 Go handler 测试。

## 测试
- `go test ./services/terminal-gateway/...` 通过。
- `.venv/bin/python -m pytest services/api/tests/test_terminal_vertical_slice.py` 通过。

## 风险
- 尚未运行真实浏览器断线 E2E。
```

## 不应单独提交的变更

以下变更通常不应单独提交，除非有明确维护目的：

- 只更新生成缓存。
- 只格式化大量无关文件。
- 只更新状态文档但没有对应代码或测试证据。
- 混合多个无关主题，例如同时改 Gateway 协议、Web 视觉和数据库迁移。
- 删除用户未要求删除的文件或回滚他人变更。

## 发布标签

当前项目尚未进入正式发布阶段。后续建议版本标签：

```text
v0.1.0-terminal-slice
v0.2.0-compose-e2e
v0.3.0-k8s-lab-plane
```

发布前需要：

- API、Go、Web 全量测试通过。
- Compose live smoke 通过。
- Kubernetes live smoke 通过。
- 内容 CI 通过。
- 安全负例测试通过。
- 状态文档和追踪矩阵更新。
- CHANGELOG 或发布说明记录已知限制。

## 自动化 agent 协作要求

后续 agent 修改仓库时必须：

- 先读规格、README、状态和追踪矩阵。
- 不擅自删除用户修改。
- 不提交生成物、密钥和本地数据库。
- 不把未验证能力写成已完成。
- 遇到远程推送需求但缺少 remote URL 时，先完成本地提交，再向用户索要远程地址。
- Git 写操作需要在受控环境中执行并检查 `git status`。
