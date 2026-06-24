# ADR 0007：外部 Oracle 边界

## 状态

已采纳并测试。

## 背景

Shell hook 和终端文本会受学生影响，只能作为弱证据。正式客观通过必须来自学生控制边界之外。

## 决策

P1 API 只通过 `/internal/oracle/attempts/{id}/observations` 接收 Oracle 观测，并要求对规范化 JSON 进行 HMAC 签名。签名后的 `oracle.observed` 事件标记为 S4 证据，并用于确定性评分。

## 影响

篡改的 Oracle payload 会被拒绝。示例 validator 通过外部 HTTP 谓词观察 target 状态，并生成供 API 接入的证据 payload。

## 回滚

可从共享 HMAC 迁移到工作负载身份或非对称签名，但保持 `oracle.observed` 的证据语义不变。
