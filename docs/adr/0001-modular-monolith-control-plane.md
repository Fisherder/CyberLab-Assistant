# ADR 0001：模块化单体控制平面

## 状态

P0/P1 已采纳。

## 背景

[cla_terminal_first_complete_development_spec.html](/Users/fisherder/Desktop/研究生/Security_Class_Tool/cla_terminal_first_complete_development_spec.html) 建议使用 FastAPI 模块化单体承载课程、内容、Attempt、评分、申诉、审计和 Outbox 的业务事实。

## 决策

使用 `services/api` 作为业务事实所有者。该模块负责 SQLAlchemy 模型、迁移、RBAC、幂等、终端票据签发、Oracle 事件接入、GradeRevision、Appeal、Audit 和 Outbox 写入。

## 影响

P0/P1 的事务保持在本地进程内，便于测试和演进。终端字节中继、环境调和和 Agent 执行仍是独立部署边界。若后续吞吐或团队所有权压力变大，可在 OpenAPI/Protobuf 契约之后逐步拆分模块。

## 回滚

按模块逐个抽离，同时保持 PostgreSQL 作为迁移期间的事实来源。
