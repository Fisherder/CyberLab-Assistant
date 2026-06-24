# ADR 0008：GUI 只预留，不进入一期运行

## 状态

已采纳，并通过 API 拒绝路径测试。

## 背景

一期不得实现 GUI、RDP/VNC、Guacamole、视觉观察器、桌面环境、IDA/Burp 插件或文档模拟器。

## 决策

契约保留 `WorkspaceType = TERMINAL | REMOTE_DESKTOP | SIMULATED`，但运行时代码只接受 `TERMINAL`。其它类型返回 `WORKSPACE_FEATURE_NOT_ENABLED`。应用、服务、部署和题目文件中不引入 GUI 运行依赖。

## 影响

后续 GUI 能复用 Attempt/Session/Event 抽象，但不会在一期引入空服务或假实现。

## 回滚

只有在明确放弃未来 GUI 扩展时，才移除禁用的枚举值。
