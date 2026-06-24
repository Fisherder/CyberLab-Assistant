# ADR 0004：Gateway 不持有 Kubernetes 凭据

## 状态

已采纳。

## 背景

规格禁止终端网关持有通用 Kubernetes 管理凭据。

## 决策

`services/terminal-gateway` 通过 API 消费终端票据，拿到不透明路由映射后连接 sessiond。Gateway 不使用 `kubectl exec`，不从浏览器接收 Pod 名称或容器 IP，也不挂载 ServiceAccount Token。

## 影响

Gateway 保持为字节中继和流控边界。路由解析属于内部、可审计流程。Kubernetes 路由由 environment-controller 和控制平面路由注册表负责。

## 回滚

若生产路由机制变化，应保持票据和内部路由 API 稳定，只替换路由解析实现。
