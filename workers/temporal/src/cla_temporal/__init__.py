"""P1 的 Temporal 工作流边界。

本地 P1 测试暂时使用 FastAPI 服务内的确定性进程内替代路径。
生产环境中的 SessionLifecycle、PublishChallenge 和 Grading
工作流必须在这里拥有宏观状态，所有外部副作用都放入 Activity。
"""
