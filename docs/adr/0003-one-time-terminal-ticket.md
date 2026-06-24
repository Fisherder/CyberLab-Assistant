# ADR 0003：一次性终端票据

## 状态

已采纳，并由 `services/api/tests/test_terminal_vertical_slice.py` 覆盖。

## 背景

浏览器不能获得 Pod 名称、容器 IP、Kubernetes 凭据、会话密码或 `route_ref`，只能持有短期不透明终端票据。

## 决策

`services/api` 签发 HS256 JWT 票据，声明包含 `iss=cla-api`、`aud=cla-terminal-gateway`、`sub`、`tenant_id`、`attempt_id`、`session_id`、`session_epoch`、`route_ref`、`permissions`、`nonce`、`iat` 和 `exp`。票据 60 秒过期，内部 Gateway 消费端点会把 nonce 从 `ISSUED` 原子更新为 `CONSUMED`。

## 影响

前端响应只包含 `ticket`、`websocketUrl`、终端尺寸、重连策略和用户可见策略。内部路由只在 Gateway 消费票据后可见。

## 回滚

可把本地 SQL nonce 存储替换为 Redis `SETNX`，但保持票据声明形状和测试不变。
