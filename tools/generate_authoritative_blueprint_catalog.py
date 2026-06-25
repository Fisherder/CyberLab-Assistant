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
        "domains": ["WEB", "REVERSE", "PWN"],
        "usageNote": "只引用公开分类体系和题型覆盖方向，不复制题目材料。",
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
        "domains": ["PWN", "REVERSE", "WEB"],
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


def main() -> None:
    entries = []
    entries.extend(_domain_entries("WEB", WEB_ARCHETYPES, WEB_VARIANTS, "web-python-service"))
    entries.extend(_domain_entries("REVERSE", REVERSE_ARCHETYPES, REVERSE_VARIANTS, "reverse-cli-binary"))
    entries.extend(_domain_entries("PWN", PWN_ARCHETYPES, PWN_VARIANTS, "pwn-cli-service"))
    catalog = {
        "catalogVersion": "2026.06-authoritative-blueprints",
        "description": "CLA 权威来源题型蓝图库。该文件记录题型、知识点、组合关系和生成模板，不复制外部平台题面、附件、flag 或题解。",
        "sources": SOURCES,
        "qualityGate": {
            "minimumPerCategory": {"WEB": 50, "REVERSE": 50, "PWN": 50},
            "copyPolicy": "no-statement-no-flag-no-attachment-no-solution",
            "workspaceType": "TERMINAL",
        },
        "entries": entries,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "# 该文件由 tools/generate_authoritative_blueprint_catalog.py 生成。\n"
        "# 请修改生成脚本后重新生成，不要手工维护 150 条条目。\n"
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
    }[category]
    return base + [f"掌握 {slug} 题型中的 {variant} 变体"]


def _prerequisites(category: str, slug: str) -> list[str]:
    if category == "WEB":
        return ["HTTP 基础", "浏览器请求模型", "服务端输入处理"]
    if category == "REVERSE":
        return ["ELF/PE 基础", "汇编阅读", "调试器基础"]
    return ["C 语言内存模型", "Linux 进程与 ABI", "基础调试"]


def _tooling(category: str, slug: str) -> list[str]:
    if category == "WEB":
        return ["curl", "python"]
    if category == "REVERSE":
        return ["strings", "objdump", "readelf", "gdb", "python"]
    if slug in {"heap", "uaf"}:
        return ["gdb", "python", "pwntools"]
    return ["gdb", "python", "pwntools", "checksec"]


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
    return {
        "target": "受限网络服务或本地 setuid 风格模型",
        "vulnerability": f"{slug}:{variant}",
        "oracle": "外部利用成功信号与进程边界检查",
        "workspace": "pwn CLI 工具容器",
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
    return {"WEB": web, "REVERSE": reverse, "PWN": pwn}[category][slug]


def _combination_notes(category: str, slug: str) -> str:
    if category == "WEB":
        return "可与认证、访问控制、API 或业务逻辑蓝图组合成多阶段 Web 靶场。"
    if category == "REVERSE":
        return "可作为前置逆向阶段，产出密钥、协议或二进制约束供后续利用阶段使用。"
    return "可与逆向或 Web 初始入口组合，形成从信息恢复到利用执行的复合题。"


if __name__ == "__main__":
    main()
