# ADR 0005：sessiond 以 non-root 创建 PTY

## 状态

已采纳并通过 Go 测试验证。

## 背景

`cla-sessiond` 运行在 workspace 容器内，负责创建受限 PTY，不访问控制平面，并且必须以 non-root 用户运行。

## 决策

`runtime/sessiond` 仅在 `os.Geteuid() != 0` 时启动，监听会话端口，在 `/workspace` 中启动配置的 shell，并向 Gateway 中继 PTY 字节。workspace Dockerfile 使用 non-root `student` 用户。

## 影响

sessiond 没有集群凭据，不能评分、部署、重置或调用 Agent 工具。Shell hook 事件仍然只是弱证据。

## 回滚

可把 TCP 中继替换为 mTLS/gRPC，但必须保留 non-root PTY 和无控制面访问边界。
