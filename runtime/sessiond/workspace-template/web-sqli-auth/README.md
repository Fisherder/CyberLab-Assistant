# CLA Web SQLi Auth 实验工作区

这里是学生终端的工作区。正常情况下，`ls` 只应该看到和当前题目有关的文件，不应该看到宿主机 `/tmp`、系统缓存、其他项目或历史调试文件。

## 当前题目

- 题目：登录逻辑与输入信任边界
- 类型：Web 安全终端实验
- 目标：观察登录接口行为，验证输入是否被不安全地拼接到查询逻辑中，并用自己的话解释根因和修复方式。

## 可用环境变量

```bash
echo "$TARGET_BASE_URL"
```

本地开发环境默认目标地址是：

```text
http://127.0.0.1:18080
```

## 建议起步命令

```bash
curl -i "$TARGET_BASE_URL/healthz"
curl -i -X POST "$TARGET_BASE_URL/login" -d "username=alice&password=wrong"
```

不要在终端里输入、打印或提交自己的密码、Cookie、Authorization、token 等敏感信息。
