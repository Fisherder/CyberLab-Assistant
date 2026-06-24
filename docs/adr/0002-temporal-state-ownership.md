# ADR 0002：Temporal 状态所有权

## 状态

已采纳，P1 使用本地替代路径。

## 背景

规格要求题目发布、会话生命周期和评分发布由确定性 Workflow 负责。当前工作区起步时没有可运行的 Temporal Runtime。

## 决策

生产形态由 `workers/temporal` 拥有宏观工作流。P1 本地测试中，`services/api` 提供最小确定性替代：Attempt 创建、本地 LabSession Ready 和成绩发布在同步事务中完成。

## 影响

当前可运行切片能验证领域不变量，同时不伪造未经验证的 Temporal 部署。P2/P3 必须把长时间重试、审批等待和补偿逻辑迁入 Temporal Activity 与 Workflow。

## 回滚

Temporal Worker 接通后，在 `CLA_ENV=production` 下关闭同步本地路径。
