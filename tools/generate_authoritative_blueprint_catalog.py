from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import yaml


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "content" / "challenge-blueprints" / "authoritative-catalog.yaml"


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data) -> bool:  # type: ignore[override]
        return True


SOURCES = [
    {
        "id": "owasp-top10",
        "name": "OWASP Top 10",
        "url": "https://owasp.org/Top10/",
        "domains": ["WEB"],
        "usageNote": "只引用公开风险分类和教学方向，不复制文章原文、示例 payload 或第三方素材。",
    },
    {
        "id": "owasp-api-security-top10",
        "name": "OWASP API Security Top 10",
        "url": "https://owasp.org/API-Security/",
        "domains": ["WEB"],
        "usageNote": "只引用 API 风险分类和安全控制点，不复制具体题面或平台内容。",
    },
    {
        "id": "owasp-juice-shop",
        "name": "OWASP Juice Shop",
        "url": "https://owasp.org/www-project-juice-shop/",
        "domains": ["WEB"],
        "usageNote": "只引用教学靶场覆盖方向，不复制题面、答案、附件、flag 或平台素材。",
    },
    {
        "id": "portswigger-web-security-academy",
        "name": "PortSwigger Web Security Academy",
        "url": "https://portswigger.net/web-security/all-labs",
        "domains": ["WEB"],
        "usageNote": "只引用公开知识点分类和实验主题，不复制题面、答案、payload 或平台素材。",
    },
    {
        "id": "owasp-webgoat",
        "name": "OWASP WebGoat",
        "url": "https://owasp.org/www-project-webgoat/",
        "domains": ["WEB"],
        "usageNote": "只提炼课程型漏洞主题和教学目标，不复制具体课程文本。",
    },
    {
        "id": "picoctf-practice",
        "name": "picoCTF Practice / picoGym",
        "url": "https://picoctf.org/",
        "domains": ["WEB", "REVERSE", "PWN", "CRYPTO", "FORENSICS", "MISC"],
        "usageNote": "只引用公开分类体系和题型覆盖方向，不复制题目材料。",
    },
    {
        "id": "cryptohack",
        "name": "CryptoHack Challenges",
        "url": "https://cryptohack.org/challenges/",
        "domains": ["CRYPTO"],
        "usageNote": "只引用公开密码学训练分类，不复制具体题面、密文或解法。",
    },
    {
        "id": "ctf101",
        "name": "CTF101",
        "url": "https://ctf101.org/",
        "domains": ["WEB", "REVERSE", "PWN", "CRYPTO", "FORENSICS", "MISC"],
        "usageNote": "只引用 CTF 入门知识分类，不复制练习材料或答案。",
    },
    {
        "id": "root-me-challenges",
        "name": "Root-Me Challenges",
        "url": "https://www.root-me.org/en/Challenges/",
        "domains": ["WEB", "REVERSE", "PWN", "CRYPTO", "FORENSICS", "MISC"],
        "usageNote": "只引用公开挑战分类体系，不复制题面、附件、flag 或解法。",
    },
    {
        "id": "pwn-college",
        "name": "pwn.college",
        "url": "https://pwn.college/",
        "domains": ["PWN", "REVERSE"],
        "usageNote": "只引用模块化训练主题，不复制关卡内容或远端环境。",
    },
    {
        "id": "rop-emporium",
        "name": "ROP Emporium",
        "url": "https://ropemporium.com/",
        "domains": ["PWN"],
        "usageNote": "只引用 ROP 技术阶梯，不复制二进制或题面。",
    },
    {
        "id": "microcorruption",
        "name": "Microcorruption",
        "url": "https://microcorruption.com/",
        "domains": ["REVERSE"],
        "usageNote": "只引用嵌入式逆向训练方向，不复制关卡文本或固件。",
    },
    {
        "id": "crackmes-one",
        "name": "crackmes.one",
        "url": "https://crackmes.one/",
        "domains": ["REVERSE"],
        "usageNote": "只引用 crackme 题型和难度覆盖方向，不复制样本。",
    },
    {
        "id": "overthewire-wargames",
        "name": "OverTheWire Wargames",
        "url": "https://overthewire.org/wargames/",
        "domains": ["PWN", "REVERSE", "WEB", "CRYPTO", "MISC"],
        "usageNote": "只引用 wargame 训练类别，不复制关卡口令、题面或服务器内容。",
    },
    {
        "id": "pwnable-kr",
        "name": "pwnable.kr",
        "url": "https://pwnable.kr/",
        "domains": ["PWN"],
        "usageNote": "只引用二进制利用训练主题，不复制题目二进制或解法。",
    },
]


WEB_ARCHETYPES = [
    ("sqli", "SQL 注入", ["portswigger-web-security-academy", "owasp-webgoat"], ["curl", "python"]),
    ("xss", "跨站脚本", ["portswigger-web-security-academy", "owasp-webgoat"], ["curl", "python"]),
    ("auth", "认证与会话逻辑", ["portswigger-web-security-academy", "owasp-webgoat"], ["curl", "python"]),
    ("access", "访问控制", ["portswigger-web-security-academy"], ["curl", "python"]),
    ("ssrf", "SSRF 与内网边界", ["portswigger-web-security-academy"], ["curl", "python"]),
    ("file", "文件上传与路径遍历", ["portswigger-web-security-academy", "owasp-webgoat"], ["curl", "python"]),
    ("ssti", "模板与反序列化", ["portswigger-web-security-academy", "owasp-webgoat"], ["curl", "python"]),
    ("xxe", "XML 与解析器安全", ["portswigger-web-security-academy", "owasp-webgoat"], ["curl", "python"]),
    ("race", "竞态、缓存与业务逻辑", ["portswigger-web-security-academy"], ["curl", "python"]),
    ("api", "API 与云原生 Web 安全", ["portswigger-web-security-academy", "picoctf-practice"], ["curl", "python"]),
    ("csrf", "CSRF 与浏览器信任边界", ["portswigger-web-security-academy", "owasp-top10"], ["curl", "python"]),
    ("deserialization", "反序列化与对象注入", ["portswigger-web-security-academy", "owasp-top10", "owasp-webgoat"], ["curl", "python"]),
    ("command", "命令注入与服务端执行", ["portswigger-web-security-academy", "owasp-top10"], ["curl", "python"]),
    ("nosql", "NoSQL 注入与查询对象", ["portswigger-web-security-academy", "owasp-api-security-top10"], ["curl", "python"]),
    ("jwt", "JWT 与身份令牌安全", ["portswigger-web-security-academy", "owasp-api-security-top10"], ["curl", "python"]),
]

WEB_VARIANTS = {
    "sqli": ["联合查询枚举", "布尔盲注", "时间盲注", "登录绕过", "二阶注入"],
    "xss": ["反射型上下文", "存储型评论", "DOM Source/Sink", "CSP 约束绕过", "模板拼接注入"],
    "auth": ["弱重置令牌", "MFA 流程缺陷", "JWT 算法混淆", "Session Fixation", "OAuth 回调滥用"],
    "access": ["IDOR 横向越权", "垂直权限绕过", "方法级鉴权缺失", "多租户对象越界", "未公开接口遍历"],
    "ssrf": ["云元数据探测", "URL 白名单绕过", "重定向链绕过", "协议混淆", "内部管理面访问"],
    "file": ["相对路径穿越", "扩展名绕过上传", "MIME 校验绕过", "多态图片脚本", "日志投毒到包含"],
    "ssti": ["Jinja 表达式注入", "Java 反序列化", "Node 原型污染", "YAML 不安全加载", "模板沙箱逃逸"],
    "xxe": ["本地文件读取", "盲 XXE 回连", "XInclude 注入", "JSON/XML 差异解析", "实体膨胀防护"],
    "race": ["优惠券竞态", "库存扣减竞态", "Web Cache Poisoning", "Cache Deception", "状态机跳步"],
    "api": ["GraphQL 过度暴露", "Mass Assignment", "CORS 错配", "速率限制绕过", "Webhook 签名缺陷"],
    "csrf": ["状态变更表单", "SameSite 边界", "Referer 校验缺失", "双提交 Cookie 缺陷", "JSON CSRF"],
    "deserialization": ["Python Pickle 对象注入", "Java gadget 链线索", "PHP Phar 元数据", "签名缺失会话对象", "类型混淆反序列化"],
    "command": ["Shell 拼接执行", "参数注入", "环境变量污染", "换行命令分隔", "文件名命令注入"],
    "nosql": ["Mongo 查询对象注入", "正则条件绕过", "JSON 类型混淆", "聚合管道滥用", "认证查询绕过"],
    "jwt": ["none 算法拒绝", "弱密钥爆破", "kid 路径注入", "JWK 注入", "声明边界绕过"],
}

REVERSE_ARCHETYPES = [
    ("strings", "字符串与常量恢复", ["picoctf-practice", "crackmes-one"]),
    ("keygen", "注册码与 Keygen", ["crackmes-one", "picoctf-practice"]),
    ("antidebug", "反调试与反分析", ["crackmes-one"]),
    ("packing", "壳与自解密", ["crackmes-one", "picoctf-practice"]),
    ("cff", "控制流混淆", ["crackmes-one"]),
    ("vm", "虚拟机与字节码", ["crackmes-one", "picoctf-practice"]),
    ("crypto", "逆向中的密码误用", ["picoctf-practice", "crackmes-one"]),
    ("mobile", "移动端逆向", ["picoctf-practice", "crackmes-one"]),
    ("stripped", "Go/Rust/静态链接逆向", ["picoctf-practice", "crackmes-one"]),
    ("embedded", "嵌入式与微控制器逆向", ["microcorruption", "picoctf-practice"]),
]

REVERSE_VARIANTS = {
    "strings": ["XOR 字符串", "表驱动解码", "宽字符混淆", "运行时拼接", "资源节提取"],
    "keygen": ["线性校验", "CRC 派生", "多段约束", "日期绑定", "离线许可证"],
    "antidebug": ["ptrace 检测", "时间差检测", "断点扫描", "父进程检查", "异常处理陷阱"],
    "packing": ["UPX 变体", "自解密段", "压缩资源", "分段加载", "导入表重建"],
    "cff": ["Flattening 状态机", "Opaque Predicate", "跳表混淆", "异常流控制", "间接调用链"],
    "vm": ["栈式 VM", "寄存器式 VM", "混合指令 VM", "字节码 Patch", "解释器还原"],
    "crypto": ["硬编码密钥", "ECB 模式误用", "自定义 Base 编码", "弱 PRNG", "校验和碰撞"],
    "mobile": ["APK 字符串恢复", "JNI 断点", "证书 Pinning 绕过", "资源混淆", "DEX 控制流"],
    "stripped": ["Go 符号恢复", "Rust panic 线索", "静态链接 libc", "无符号 C++", "交叉引用恢复"],
    "embedded": ["MSP430 固件", "内存映射寄存器", "串口协议", "Bootloader 检查", "固件差分"],
}

PWN_ARCHETYPES = [
    ("stack", "栈溢出与 ret2win", ["rop-emporium", "pwn-college", "picoctf-practice"]),
    ("rop", "ROP 与 ret2libc", ["rop-emporium", "pwn-college"]),
    ("format", "格式化字符串", ["pwn-college", "picoctf-practice", "pwnable-kr"]),
    ("heap", "堆利用与 tcache", ["pwn-college", "pwnable-kr"]),
    ("uaf", "Use-After-Free", ["pwn-college", "pwnable-kr"]),
    ("integer", "整数与边界错误", ["pwn-college", "picoctf-practice"]),
    ("shellcode", "Shellcode 与 Seccomp", ["pwn-college", "pwnable-kr"]),
    ("pie", "PIE/Canary/NX 绕过", ["pwn-college", "rop-emporium"]),
    ("sandbox", "沙箱逃逸与文件能力", ["pwn-college", "overthewire-wargames"]),
    ("kernelish", "内核风格用户态模型", ["pwn-college", "pwnable-kr"]),
]

PWN_VARIANTS = {
    "stack": ["ret2win 基础", "偏移测量", "栈迁移前置", "部分覆盖返回地址", "环境变量影响"],
    "rop": ["ret2plt 泄露", "ret2libc system", "CSU Gadget", "栈对齐", "ROP Pivot"],
    "format": ["栈泄露", "任意地址写", "GOT 改写", "Blind Format", "宽字符格式化"],
    "heap": ["tcache poisoning", "fastbin dup", "unsorted bin leak", "house of spirit", "chunk overlap"],
    "uaf": ["函数指针复用", "vtable 劫持", "double free", "引用计数错误", "对象类型混淆"],
    "integer": ["长度截断", "符号转换", "乘法溢出", "数组索引越界", "负数尺寸"],
    "shellcode": ["栈可执行", "NX 下 mprotect", "seccomp 允许集", "ORW Shellcode", "多架构 Shellcode"],
    "pie": ["Canary 泄露", "PIE 基址恢复", "RELRO 约束", "Partial RELRO GOT", "ASLR 暴力窗口"],
    "sandbox": ["chroot 误用", "路径竞态", "软链接 TOCTOU", "文件描述符泄露", "capability 误配"],
    "kernelish": ["ioctl 模型", "copy_from_user 模拟", "slab 风格对象", "竞态锁缺失", "引用生命周期"],
}


CRYPTO_ARCHETYPES = [
    ("encoding", "编码与表示", ["cryptohack", "picoctf-practice", "ctf101"], ["python"]),
    ("classical", "古典密码", ["cryptohack", "picoctf-practice", "ctf101"], ["python"]),
    ("xor", "XOR 与流式异或", ["cryptohack", "picoctf-practice"], ["python"]),
    ("hash", "哈希与完整性", ["cryptohack", "picoctf-practice"], ["python", "hashcat"]),
    ("symmetric", "对称加密模式", ["cryptohack", "picoctf-practice"], ["python", "openssl"]),
    ("padding", "填充与模式 Oracle", ["cryptohack", "ctf101"], ["python", "openssl"]),
    ("rsa", "RSA 公钥密码", ["cryptohack", "picoctf-practice"], ["python", "sage"]),
    ("dh", "Diffie-Hellman 密钥交换", ["cryptohack"], ["python", "sage"]),
    ("ecc", "椭圆曲线密码", ["cryptohack"], ["python", "sage"]),
    ("prng", "随机数与密钥生成", ["cryptohack", "picoctf-practice"], ["python"]),
]

CRYPTO_VARIANTS = {
    "encoding": ["Base64/Base85 多层编码", "Hex 与字节序", "Morse 与培根编码", "二维码与二进制表示", "Unicode 混淆"],
    "classical": ["凯撒移位", "维吉尼亚密钥恢复", "替换密码频率分析", "栅栏与置换密码", "仿射密码"],
    "xor": ["单字节 XOR", "重复密钥 XOR", "已知明文 XOR", "多密文 Two-Time Pad", "流密钥复用"],
    "hash": ["弱哈希碰撞", "长度扩展攻击", "盐值缺失爆破", "HMAC 用法错误", "Merkle 树校验"],
    "symmetric": ["AES ECB 模式识别", "CBC IV 复用", "CTR Nonce 复用", "GCM Tag 校验错误", "密钥派生参数弱"],
    "padding": ["PKCS#7 填充验证", "CBC Padding Oracle", "错误消息侧信道", "MAC-then-Encrypt", "块边界构造"],
    "rsa": ["小指数广播", "共模攻击", "低熵素数", "Wiener 小私钥", "CRT 故障线索"],
    "dh": ["小子群攻击", "离散对数入门", "参数注入", "复用私钥", "中间人协商"],
    "ecc": ["曲线参数识别", "点乘基础", "无效曲线攻击", "ECDSA Nonce 重用", "EdDSA 签名线索"],
    "prng": ["时间种子恢复", "LCG 参数恢复", "Mersenne Twister 状态恢复", "Token 可预测", "随机数偏差统计"],
}

FORENSICS_ARCHETYPES = [
    ("file", "文件格式与魔数", ["picoctf-practice", "ctf101", "root-me-challenges"]),
    ("image", "图片隐写与元数据", ["picoctf-practice", "ctf101", "root-me-challenges"]),
    ("pcap", "网络流量取证", ["picoctf-practice", "ctf101", "root-me-challenges"], ["tshark", "tcpdump"]),
    ("memory", "内存取证", ["ctf101", "root-me-challenges"], ["volatility", "strings"]),
    ("disk", "磁盘与文件系统", ["picoctf-practice", "ctf101", "root-me-challenges"], ["file", "strings"]),
    ("logs", "日志时间线分析", ["ctf101", "root-me-challenges"], ["grep", "awk", "python"]),
    ("malware", "恶意样本静态取证", ["picoctf-practice", "root-me-challenges"], ["file", "strings"]),
    ("audio", "音频与信号取证", ["picoctf-practice", "ctf101"], ["python"]),
    ("osint", "OSINT 线索分析", ["picoctf-practice", "root-me-challenges"], ["python"]),
    ("document", "文档与元数据取证", ["picoctf-practice", "ctf101", "root-me-challenges"], ["exiftool", "strings"]),
]

FORENSICS_VARIANTS = {
    "file": ["文件头修复", "嵌套归档识别", "文件尾数据提取", "多格式伪装", "损坏压缩包修复"],
    "image": ["EXIF 元数据", "LSB 隐写", "调色板异常", "Alpha 通道隐藏", "拼图与像素重排"],
    "pcap": ["HTTP 会话重组", "DNS 隧道线索", "TLS SNI 与证书", "SMB/FTP 文件恢复", "异常扫描流量"],
    "memory": ["进程列表恢复", "网络连接定位", "命令历史提取", "恶意进程线索", "凭据痕迹定位"],
    "disk": ["删除文件恢复", "分区表分析", "文件系统时间线", "隐藏目录线索", "镜像挂载检查"],
    "logs": ["认证失败时间线", "Web 访问日志", "容器日志关联", "系统审计事件", "多源时间偏移"],
    "malware": ["字符串 IOC 提取", "导入表分析", "配置块定位", "简单解包线索", "沙箱行为摘要"],
    "audio": ["频谱图隐藏", "DTMF 识别", "反转音频", "采样率异常", "无线调制线索"],
    "osint": ["图片地理线索", "公开用户名关联", "域名历史线索", "时间地点推断", "社交公开信息核验"],
    "document": ["PDF 元数据", "Office 宏线索", "隐藏文本层", "修订记录", "嵌入对象提取"],
}

MISC_ARCHETYPES = [
    ("linux", "Linux 基础与文件系统", ["picoctf-practice", "overthewire-wargames", "ctf101"]),
    ("shell", "Shell 管道与文本处理", ["picoctf-practice", "overthewire-wargames", "ctf101"]),
    ("scripting", "Python 自动化脚本", ["picoctf-practice", "ctf101"]),
    ("git", "Git 与历史记录", ["picoctf-practice", "ctf101"]),
    ("regex", "正则与文本解析", ["picoctf-practice", "ctf101"]),
    ("container", "容器与运行环境基础", ["picoctf-practice", "root-me-challenges"]),
    ("permission", "权限与能力模型", ["overthewire-wargames", "root-me-challenges"]),
    ("data", "数据格式与结构化处理", ["picoctf-practice", "ctf101"]),
    ("network", "网络基础工具", ["picoctf-practice", "overthewire-wargames", "ctf101"]),
    ("encoding", "通用编码解码", ["picoctf-practice", "ctf101"]),
    ("cloud", "云服务与身份配置", ["root-me-challenges", "ctf101"]),
    ("k8s", "Kubernetes 与容器编排安全", ["pwn-college", "root-me-challenges"]),
    ("ad", "Active Directory 与企业身份基础", ["root-me-challenges", "ctf101"]),
    ("supply", "软件供应链与依赖安全", ["root-me-challenges", "ctf101"]),
]

MISC_VARIANTS = {
    "linux": ["目录遍历", "隐藏文件", "软硬链接", "环境变量", "进程与端口查看"],
    "shell": ["grep/sed/awk 管道", "find 条件搜索", "xargs 批处理", "重定向与 here-doc", "排序去重统计"],
    "scripting": ["批量请求脚本", "文件批处理", "简单爆破脚本", "字节转换脚本", "日志解析脚本"],
    "git": ["提交历史恢复", "分支差异", "误删文件恢复", "Stash 线索", "对象库检查"],
    "regex": ["模式提取", "日志字段拆分", "贪婪匹配陷阱", "多行匹配", "输入校验边界"],
    "container": ["镜像层查看", "环境变量检查", "文件挂载线索", "入口命令分析", "资源限制观察"],
    "permission": ["setuid 线索", "sudo 规则阅读", "文件 ACL", "capability 检查", "umask 影响"],
    "data": ["JSON jq 查询", "CSV 聚合", "YAML 配置阅读", "SQLite 查询", "二进制结构解析"],
    "network": ["nc 交互", "端口探测", "HTTP Header 观察", "DNS 查询", "TLS 证书查看"],
    "encoding": ["Base64 解码", "URL 编码", "Hex 转换", "二进制转文本", "多层编码识别"],
    "cloud": ["IAM 最小权限", "对象存储公开读", "元数据凭据边界", "临时凭证过期", "策略条件误配"],
    "k8s": ["ServiceAccount Token 暴露", "RBAC 过宽", "Secret 错误挂载", "NetworkPolicy 缺失", "镜像准入失败"],
    "ad": ["Kerberos 票据基础", "LDAP 查询过滤", "弱口令喷洒日志", "组权限继承", "共享目录线索"],
    "supply": ["依赖锁文件漂移", "恶意安装脚本", "SBOM 组件定位", "镜像 digest 校验", "CI Secret 暴露痕迹"],
}


def main() -> None:
    entries = []
    entries.extend(_domain_entries("WEB", WEB_ARCHETYPES, WEB_VARIANTS, "web-python-service"))
    entries.extend(_domain_entries("REVERSE", REVERSE_ARCHETYPES, REVERSE_VARIANTS, "reverse-cli-binary"))
    entries.extend(_domain_entries("PWN", PWN_ARCHETYPES, PWN_VARIANTS, "pwn-cli-service"))
    entries.extend(_domain_entries("CRYPTO", CRYPTO_ARCHETYPES, CRYPTO_VARIANTS, "crypto-cli-task"))
    entries.extend(_domain_entries("FORENSICS", FORENSICS_ARCHETYPES, FORENSICS_VARIANTS, "forensics-cli-artifact"))
    entries.extend(_domain_entries("MISC", MISC_ARCHETYPES, MISC_VARIANTS, "misc-cli-task"))
    catalog = {
        "catalogVersion": "2026.06-authoritative-blueprints",
        "description": "CLA 权威来源题型蓝图库。该文件记录题型、知识点、组合关系和生成模板，不复制外部平台题面、附件、flag 或题解。",
        "sources": SOURCES,
        "qualityGate": {
            "minimumPerCategory": {
                "WEB": 50,
                "REVERSE": 50,
                "PWN": 50,
                "CRYPTO": 50,
                "FORENSICS": 50,
                "MISC": 50,
            },
            "copyPolicy": "no-statement-no-flag-no-attachment-no-solution",
            "workspaceType": "TERMINAL",
        },
        "entries": entries,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "# 该文件由 tools/generate_authoritative_blueprint_catalog.py 生成。\n"
        "# 请修改生成脚本后重新生成，不要手工维护条目。\n"
        + yaml.dump(
            catalog,
            Dumper=NoAliasDumper,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )
    counts = {}
    for entry in entries:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    print({"output": str(OUTPUT), "count": len(entries), "counts": counts})


def _domain_entries(category: str, archetypes: list[tuple], variants: dict[str, list[str]], template: str) -> list[dict]:
    entries = []
    for archetype_index, archetype in enumerate(archetypes, start=1):
        slug, title, sources = archetype[:3]
        tools = archetype[3] if len(archetype) > 3 else []
        for variant_index, variant in enumerate(variants[slug], start=1):
            entry_id = f"{category.lower()}-{slug}-{variant_index:02d}"
            difficulty = 1 + ((archetype_index + variant_index - 2) % 5)
            minutes = 45 + 15 * min(4, difficulty)
            entries.append(
                {
                    "id": entry_id,
                    "title": f"{title}：{variant}",
                    "category": category,
                    "sourceRefs": sources,
                    "archetype": slug,
                    "variant": variant,
                    "workspaceType": "TERMINAL",
                    "difficulty": difficulty,
                    "expectedMinutes": minutes,
                    "isolationTier": 2 if category == "PWN" and difficulty >= 4 else 1,
                    "tags": _tags(category, slug, variant),
                    "learningObjectives": _objectives(category, slug, variant),
                    "prerequisites": _prerequisites(category, slug),
                    "workspaceCapabilities": sorted(set(tools + _tooling(category, slug))),
                    "components": _components(category, slug, variant),
                    "composition": {
                        "group": f"{category.lower()}-{slug}",
                        "complexity": difficulty,
                        "compatibleGroups": _compatible_groups(category, slug),
                        "canBeSubChallenge": True,
                        "combinationNotes": _combination_notes(category, slug),
                    },
                    "generator": {
                        "kind": "parameterized-template",
                        "template": template,
                        "parameters": {
                            "archetype": slug,
                            "variant": variant,
                            "difficulty": difficulty,
                        },
                    },
                    "safety": {
                        "noExternalInternetRequired": True,
                        "noDynamicSecretInPrompt": True,
                        "requiresTeacherApproval": True,
                    },
                }
            )
    return entries


def _tags(category: str, slug: str, variant: str) -> list[str]:
    return [category, slug, variant.replace(" ", "-").lower(), "authoritative-blueprint"]


def _objectives(category: str, slug: str, variant: str) -> list[str]:
    base = {
        "WEB": ["定位输入信任边界", "构造最小验证请求", "解释漏洞影响和修复建议"],
        "REVERSE": ["恢复关键控制流", "还原校验逻辑", "给出可复现实验证据"],
        "PWN": ["识别内存破坏原语", "构造稳定利用路径", "解释缓解机制影响"],
        "CRYPTO": ["识别密码原语", "还原加解密或校验过程", "给出可复现脚本证据"],
        "FORENSICS": ["提取可信证据", "还原事件线索", "说明取证结论依据"],
        "MISC": ["熟练使用终端工具", "构造可复现解题流程", "解释命令和数据处理依据"],
    }[category]
    return base + [f"掌握 {slug} 题型中的 {variant} 变体"]


def _prerequisites(category: str, slug: str) -> list[str]:
    if category == "WEB":
        return ["HTTP 基础", "浏览器请求模型", "服务端输入处理"]
    if category == "REVERSE":
        return ["ELF/PE 基础", "汇编阅读", "调试器基础"]
    if category == "PWN":
        return ["C 语言内存模型", "Linux 进程与 ABI", "基础调试"]
    if category == "CRYPTO":
        return ["Python 基础", "字节与编码", "基础数论或离散数学"]
    if category == "FORENSICS":
        return ["Linux 文件操作", "证据链意识", "常见文件和网络协议基础"]
    return ["Linux 命令行", "文本处理基础", "可复现记录习惯"]


def _tooling(category: str, slug: str) -> list[str]:
    if category == "WEB":
        return ["curl", "python"]
    if category == "REVERSE":
        return ["strings", "objdump", "readelf", "gdb", "python"]
    if category == "PWN" and slug in {"heap", "uaf"}:
        return ["gdb", "python", "pwntools"]
    if category == "PWN":
        return ["gdb", "python", "pwntools", "checksec"]
    if category == "CRYPTO":
        return ["python", "openssl", "sage"]
    if category == "FORENSICS":
        base = ["file", "strings", "python", "xxd"]
        if slug == "pcap":
            base.extend(["tshark", "tcpdump"])
        if slug in {"image", "document"}:
            base.extend(["exiftool", "binwalk"])
        if slug == "memory":
            base.append("volatility")
        return base
    return ["bash", "python", "grep", "sed", "awk", "find", "file", "jq", "git", "nc"]


def _components(category: str, slug: str, variant: str) -> dict[str, str]:
    if category == "WEB":
        return {
            "target": "HTTP 服务 + 数据存储/业务状态",
            "vulnerability": f"{slug}:{variant}",
            "oracle": "外部 HTTP 观测与服务端状态检查",
            "workspace": "受限终端工具容器",
        }
    if category == "REVERSE":
        return {
            "target": "本地 CLI 二进制或固件样本",
            "vulnerability": f"{slug}:{variant}",
            "oracle": "提交解释 + 校验输出/提取值验证",
            "workspace": "逆向 CLI 工具容器",
        }
    if category == "PWN":
        return {
            "target": "受限网络服务或本地 setuid 风格模型",
            "vulnerability": f"{slug}:{variant}",
            "oracle": "外部利用成功信号与进程边界检查",
            "workspace": "pwn CLI 工具容器",
        }
    if category == "CRYPTO":
        return {
            "target": "密文、脚本或协议转录样本",
            "vulnerability": f"{slug}:{variant}",
            "oracle": "外部脚本验证恢复明文、密钥性质或校验关系",
            "workspace": "密码学 CLI 工具容器",
        }
    if category == "FORENSICS":
        return {
            "target": "取证镜像、流量包、日志或媒体文件",
            "vulnerability": f"{slug}:{variant}",
            "oracle": "外部检查提取证据、时间线或 IOC 结构",
            "workspace": "取证 CLI 工具容器",
        }
    return {
        "target": "受限网络服务或本地 setuid 风格模型",
        "vulnerability": f"{slug}:{variant}",
        "oracle": "外部检查命令产物、数据转换或脚本输出",
        "workspace": "通用终端工具容器",
    }


def _compatible_groups(category: str, slug: str) -> list[str]:
    web = {
        "sqli": ["web-auth", "web-access", "web-api"],
        "xss": ["web-auth", "web-api", "web-race"],
        "auth": ["web-sqli", "web-access", "web-race"],
        "access": ["web-auth", "web-api", "web-file"],
        "ssrf": ["web-file", "web-api", "web-xxe"],
        "file": ["web-ssrf", "web-access", "web-ssti"],
        "ssti": ["web-file", "web-api", "web-auth"],
        "xxe": ["web-ssrf", "web-file", "web-api"],
        "race": ["web-auth", "web-api", "web-access"],
        "api": ["web-auth", "web-access", "web-race"],
        "csrf": ["web-auth", "web-race", "web-api"],
        "deserialization": ["web-file", "web-command", "web-auth"],
        "command": ["web-file", "web-ssti", "web-nosql"],
        "nosql": ["web-auth", "web-api", "web-sqli"],
        "jwt": ["web-auth", "web-api", "web-access"],
    }
    reverse = {
        "strings": ["reverse-keygen", "reverse-crypto"],
        "keygen": ["reverse-strings", "reverse-crypto"],
        "antidebug": ["reverse-packing", "reverse-cff"],
        "packing": ["reverse-antidebug", "reverse-strings"],
        "cff": ["reverse-vm", "reverse-antidebug"],
        "vm": ["reverse-cff", "reverse-crypto"],
        "crypto": ["reverse-keygen", "reverse-vm"],
        "mobile": ["reverse-crypto", "reverse-strings"],
        "stripped": ["reverse-strings", "reverse-cff"],
        "embedded": ["reverse-strings", "reverse-crypto"],
    }
    pwn = {
        "stack": ["pwn-rop", "pwn-pie"],
        "rop": ["pwn-stack", "pwn-pie"],
        "format": ["pwn-pie", "pwn-stack"],
        "heap": ["pwn-uaf", "pwn-pie"],
        "uaf": ["pwn-heap", "pwn-pie"],
        "integer": ["pwn-stack", "pwn-heap"],
        "shellcode": ["pwn-sandbox", "pwn-stack"],
        "pie": ["pwn-rop", "pwn-format"],
        "sandbox": ["pwn-shellcode", "pwn-integer"],
        "kernelish": ["pwn-uaf", "pwn-sandbox"],
    }
    crypto = {
        "encoding": ["crypto-classical", "misc-encoding"],
        "classical": ["crypto-encoding", "crypto-xor"],
        "xor": ["crypto-classical", "crypto-symmetric"],
        "hash": ["crypto-prng", "misc-scripting"],
        "symmetric": ["crypto-padding", "crypto-prng"],
        "padding": ["crypto-symmetric", "web-api"],
        "rsa": ["crypto-dh", "crypto-prng"],
        "dh": ["crypto-ecc", "crypto-rsa"],
        "ecc": ["crypto-dh", "crypto-prng"],
        "prng": ["crypto-symmetric", "crypto-rsa"],
    }
    forensics = {
        "file": ["forensics-disk", "forensics-document"],
        "image": ["forensics-file", "forensics-osint"],
        "pcap": ["forensics-logs", "misc-network"],
        "memory": ["forensics-malware", "forensics-logs"],
        "disk": ["forensics-file", "forensics-logs"],
        "logs": ["forensics-pcap", "misc-regex"],
        "malware": ["forensics-memory", "reverse-strings"],
        "audio": ["forensics-file", "crypto-encoding"],
        "osint": ["forensics-image", "forensics-document"],
        "document": ["forensics-file", "forensics-osint"],
    }
    misc = {
        "linux": ["misc-shell", "misc-permission"],
        "shell": ["misc-linux", "misc-regex"],
        "scripting": ["misc-data", "crypto-encoding"],
        "git": ["misc-linux", "forensics-logs"],
        "regex": ["misc-shell", "forensics-logs"],
        "container": ["misc-linux", "misc-permission"],
        "permission": ["misc-linux", "pwn-sandbox"],
        "data": ["misc-scripting", "crypto-encoding"],
        "network": ["forensics-pcap", "web-api"],
        "encoding": ["crypto-encoding", "misc-data"],
        "cloud": ["misc-container", "misc-network"],
        "k8s": ["misc-container", "misc-permission"],
        "ad": ["misc-network", "misc-regex"],
        "supply": ["misc-container", "forensics-logs"],
    }
    return {
        "WEB": web,
        "REVERSE": reverse,
        "PWN": pwn,
        "CRYPTO": crypto,
        "FORENSICS": forensics,
        "MISC": misc,
    }[category][slug]


def _combination_notes(category: str, slug: str) -> str:
    if category == "WEB":
        return "可与认证、访问控制、API 或业务逻辑蓝图组合成多阶段 Web 靶场。"
    if category == "REVERSE":
        return "可作为前置逆向阶段，产出密钥、协议或二进制约束供后续利用阶段使用。"
    if category == "PWN":
        return "可与逆向或 Web 初始入口组合，形成从信息恢复到利用执行的复合题。"
    if category == "CRYPTO":
        return "可与 Web、逆向或通用编码任务组合，形成密钥恢复或协议分析阶段。"
    if category == "FORENSICS":
        return "可作为线索提取前置阶段，与日志、流量、恶意样本或 OSINT 题组合。"
    return "可作为基础技能前置阶段，为 Web、取证、密码或二进制题提供工具链训练。"


if __name__ == "__main__":
    main()
