from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = ROOT / "docs" / "user-manuals"
ASSET_DIR = DOC_DIR / "assets"
PDF_DIR = ROOT / "output" / "pdf"
GENERATED_AT = datetime.now().strftime("%Y-%m-%d")

PDF_FONT_NAME = "CLAChinese"
PDF_FONT_FALLBACK = "STSong-Light"
ACTIVE_PDF_FONT_NAME = PDF_FONT_NAME
PDF_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
]


@dataclass(frozen=True)
class Manual:
    slug: str
    title: str
    subtitle: str
    audience: str
    pdf_name: str
    sections: list[dict[str, Any]]


def b(kind: str, content: Any = None, **kwargs: Any) -> dict[str, Any]:
    data = {"kind": kind, "content": content}
    data.update(kwargs)
    return data


def img(file_name: str, caption: str) -> dict[str, Any]:
    return b("image", file_name, caption=caption)


def teacher_manual() -> Manual:
    return Manual(
        slug="teacher-guide",
        title="CyberLab Assistant（CLA）教师端使用手册",
        subtitle="只讲教师在页面上怎么操作：看验证、发布题目、看课堂状态",
        audience="教师、助教、课程负责人",
        pdf_name="cla-teacher-guide.pdf",
        sections=[
            {
                "title": "先读这一页",
                "blocks": [
                    b(
                        "p",
                        "这份手册只面向教师实际使用，不讲代码、接口和部署。你只需要知道打开哪个页面、看哪些数字、点哪些按钮。",
                    ),
                    b(
                        "note",
                        "当前教师端已经暴露给用户的页面主要有两个：题目验证报告页、作业实时监控页。课程创建、申诉复核等后台能力目前还没有教师图形界面，所以本手册不把它们写成可点击步骤。",
                        title="当前页面范围",
                    ),
                    b(
                        "table",
                        headers=["你想做什么", "使用哪个页面", "主要按钮"],
                        rows=[
                            ["确认题目能不能发布", "验证报告", "刷新、审批发布或已发布"],
                            ["查看学生实验状态", "作业实时监控", "刷新"],
                            ["回到学生工作台", "页面左上角 Workbench", "Workbench"],
                        ],
                    ),
                ],
            },
            {
                "title": "进入教师端",
                "blocks": [
                    b(
                        "p",
                        "教师端没有单独的复杂首页。上课或演示前，管理员通常会给你教师端网址，或者先帮你登录好账号。你只需要在浏览器地址栏打开对应链接。",
                    ),
                    b(
                        "steps",
                        [
                            "打开管理员给你的系统地址。",
                            "如果看到统一登录页，按学校账号登录。",
                            "如果管理员给的是试用链接，直接打开即可。",
                            "进入教师页面后，先确认页面标题是你要看的题目或作业。",
                        ],
                    ),
                    b(
                        "note",
                        "本地演示环境默认页面地址是 http://127.0.0.1:3000。正式上课时请使用管理员提供的真实地址。",
                        title="地址说明",
                    ),
                ],
            },
            {
                "title": "查看题目验证报告",
                "blocks": [
                    b(
                        "p",
                        "题目验证报告用于确认一个题目版本是否适合发布给学生。你不需要理解所有内部细节，只要先看顶部四个数字和右上角按钮。",
                    ),
                    img(
                        "teacher-01-validation-report.png",
                        "教师端验证报告页：先看 Overall、Pass、Warn、Block，再看右上角按钮。",
                    ),
                    b(
                        "steps",
                        [
                            "打开教师端验证报告页面。",
                            "先看左上标题“验证报告”，确认下面的题目版本是本次要发布的版本。",
                            "看四个卡片：Overall、Pass、Warn、Block。",
                            "Block 如果是 0，通常表示没有阻断发布的问题。",
                            "Warn 如果不是 0，需要继续往下看警告项说明。",
                            "点击右上角“刷新”，可以重新读取最新状态。",
                            "如果右上角显示“审批发布”，并且 Block 是 0，确认无误后可以点击它发布题目。",
                            "如果右上角显示“已发布”，说明这个题目版本已经可以被作业使用。",
                        ],
                    ),
                    b(
                        "table",
                        headers=["你看到的内容", "怎么理解", "该做什么"],
                        rows=[
                            ["Overall = PASS", "整体通过", "可以继续检查 Warn 和下面的检查项"],
                            ["Overall = WARN", "有警告但未阻断", "阅读 Warn 内容，确认课堂是否可接受"],
                            ["Overall = BLOCK", "存在阻断问题", "不要发布，联系内容负责人修复"],
                            ["Block = 0", "没有阻断项", "可以进入发布判断"],
                            ["Block 大于 0", "有严重问题", "不要点击发布"],
                        ],
                    ),
                ],
            },
            {
                "title": "阅读验证项",
                "blocks": [
                    b(
                        "p",
                        "验证报告下面会列出一组检查项。教师日常只需要看每一组左侧的 PASS、WARN 或 BLOCK，以及粗体标题。灰色小标签是证据编号，保留给复核时查看。",
                    ),
                    b(
                        "steps",
                        [
                            "从上到下浏览检查项。",
                            "看到 PASS，表示这一项通过。",
                            "看到 WARN，读右侧标题，判断是否影响课堂使用。",
                            "看到 BLOCK，停止发布，把页面截图或版本号发给内容负责人。",
                            "不要把 Forbidden disclosure classes 里的词理解为泄露内容；它表示系统检查过这些风险类别。",
                        ],
                    ),
                    b(
                        "note",
                        "你不需要把证据标签复制给学生。验证报告是教师使用的质量检查页面，不是学生解题提示。",
                        title="不要发给学生",
                    ),
                ],
            },
            {
                "title": "刷新验证报告",
                "blocks": [
                    img(
                        "teacher-02-validation-refreshed.png",
                        "点击右上角“刷新”后，页面会重新加载当前验证结果。",
                    ),
                    b(
                        "steps",
                        [
                            "点击右上角“刷新”。",
                            "等待按钮恢复可点击状态。",
                            "再次查看 Overall、Warn、Block。",
                            "如果数字没有变化，说明当前报告已经是最新可见状态。",
                        ],
                    ),
                ],
            },
            {
                "title": "查看作业实时监控",
                "blocks": [
                    b(
                        "p",
                        "作业实时监控用于课堂中快速看学生是否开始、实验是否就绪、是否有人卡住。它不是监控学生隐私的页面，也不显示完整终端内容。",
                    ),
                    img(
                        "teacher-03-live-monitor.png",
                        "教师端作业实时监控页：顶部是班级统计，下面每行是一名学生的 Attempt。",
                    ),
                    b(
                        "steps",
                        [
                            "打开作业实时监控页面。",
                            "确认标题是当前作业，例如 Web SQLi Auth Practice。",
                            "看顶部五个卡片：Attempts、Ready、Stuck、Resource、Security。",
                            "如果 Ready 少于 Attempts，说明有学生实验环境还没就绪。",
                            "如果 Stuck 大于 0，可以关注对应学生，但不要直接给答案。",
                            "如果 Resource 或 Security 大于 0，优先联系助教或管理员排查。",
                            "点击右上角“刷新”，更新当前课堂状态。",
                        ],
                    ),
                    b(
                        "table",
                        headers=["卡片", "意思", "教师建议"],
                        rows=[
                            ["Attempts", "已经开始作业的学生次数", "用来确认是否都已进入实验"],
                            ["Ready", "实验环境已就绪的数量", "低于 Attempts 时关注环境问题"],
                            ["Stuck", "可能卡住的学生数量", "适合课堂巡查或提醒学生看提示"],
                            ["Resource", "资源类告警数量", "可能是环境或性能问题"],
                            ["Security", "安全类告警数量", "需要谨慎处理，不直接等同作弊"],
                        ],
                    ),
                ],
            },
            {
                "title": "查看学生行",
                "blocks": [
                    b(
                        "p",
                        "监控表格中每一行对应一个学生的当前 Attempt。教师主要看“会话”“辅助”“告警”和“最近事件”。",
                    ),
                    b(
                        "table",
                        headers=["列名", "你看到什么", "怎么处理"],
                        rows=[
                            ["学生", "学生显示名和 Attempt 编号", "需要定位学生时使用"],
                            ["会话", "READY、epoch 等状态", "READY 表示实验环境可用"],
                            ["辅助", "NORMAL、L1 SHOWN 等", "提示学生可继续尝试或查看提示"],
                            ["告警", "资源和安全数字", "非 0 时优先排查"],
                            ["最近事件", "最近活动时间", "长时间不变时可以询问学生是否遇到问题"],
                        ],
                    ),
                    b(
                        "note",
                        "辅助状态不是分数，也不是作弊判断。它只是帮助教师发现谁可能需要帮助。",
                        title="状态解释",
                    ),
                ],
            },
            {
                "title": "刷新作业实时监控",
                "blocks": [
                    img(
                        "teacher-04-live-refreshed.png",
                        "点击“刷新”后，页面会更新 Attempts、Ready 和学生列表状态。",
                    ),
                    b(
                        "steps",
                        [
                            "点击右上角“刷新”。",
                            "查看页面上方“更新”时间是否变化。",
                            "重新检查 Stuck、Resource、Security 三个数字。",
                            "课堂中建议每隔几分钟刷新一次，而不是一直盯着单个学生。",
                        ],
                    ),
                ],
            },
            {
                "title": "教师端常见问题",
                "blocks": [
                    b(
                        "table",
                        headers=["现象", "可能原因", "用户该怎么做"],
                        rows=[
                            ["页面打不开", "地址不对或服务未启动", "确认网址，联系管理员"],
                            ["验证报告显示 BLOCK", "题目还不能发布", "不要发布，截图发给内容负责人"],
                            ["审批按钮显示已发布", "题目已经发布过", "不用重复操作"],
                            ["实时监控没有学生", "学生还没点击启动，或进错作业", "让学生进入正确作业并点击启动"],
                            ["Ready 数量少", "部分实验环境未就绪", "让学生稍等，必要时联系助教"],
                            ["Stuck 数量高", "很多学生可能卡住", "给全班做方向性提醒，不要直接公布答案"],
                        ],
                    ),
                ],
            },
        ],
    )


def student_manual() -> Manual:
    return Manual(
        slug="student-guide",
        title="CyberLab Assistant（CLA）学生端使用手册",
        subtitle="从进入系统到提交答案、查看成绩、提交申诉的完整点击步骤",
        audience="网安实践课程学生",
        pdf_name="cla-student-guide.pdf",
        sections=[
            {
                "title": "先读这一页",
                "blocks": [
                    b(
                        "p",
                        "这份手册只讲你在页面上怎么用 CLA。你不需要理解后台服务、接口或部署。按截图和步骤操作即可。",
                    ),
                    b(
                        "steps",
                        [
                            "进入系统。",
                            "点击“启动”。",
                            "在黑色终端里输入命令。",
                            "需要帮助时点 L1、L2 或 L3。",
                            "在右侧输入答案并点“提交”。",
                            "点击“完整证据页”查看成绩。",
                            "如果认为某项评分有问题，填写理由并点“提交申诉”。",
                        ],
                    ),
                    b(
                        "note",
                        "当前版本没有复杂的学生首页。老师会告诉你系统地址，或给你一个已经带身份的试用链接。",
                        title="进入方式",
                    ),
                ],
            },
            {
                "title": "进入系统",
                "blocks": [
                    b(
                        "p",
                        "上课时，老师会告诉你系统地址。用浏览器打开后，你会进入学生工作台。页面左上角显示 CLA，左侧有 Terminal、Evidence、Appeal 三个入口。",
                    ),
                    img(
                        "student-01-workbench-not-started.png",
                        "刚进入学生工作台时，当前 Attempt 显示“未创建”，底部有“启动”按钮。",
                    ),
                    b(
                        "steps",
                        [
                            "打开老师给你的网址。",
                            "如果看到学校登录页，先完成登录。",
                            "如果老师给的是试用链接，直接打开即可。",
                            "看到左侧 Terminal 高亮，说明你已经在终端工作台。",
                            "看到当前 Attempt 是“未创建”，说明你还没有开始本次实验。",
                        ],
                    ),
                ],
            },
            {
                "title": "认识工作台",
                "blocks": [
                    b(
                        "table",
                        headers=["区域", "你看到什么", "用来做什么"],
                        rows=[
                            ["左侧栏", "Terminal、Evidence、Appeal", "切换终端、证据和申诉相关入口"],
                            ["顶部", "当前 Attempt、idle/connected、session", "查看实验是否已经启动"],
                            ["中间黑色区域", "终端窗口", "输入命令、查看输出"],
                            ["底部按钮", "启动、重连、重置", "启动或恢复实验环境"],
                            ["右侧辅助", "L1、L2、L3", "请求分级提示"],
                            ["右侧提交", "文本框、提交按钮", "写答案并提交"],
                            ["右侧成绩证据", "Total、完整证据页", "提交后查看成绩入口"],
                        ],
                    ),
                    b(
                        "note",
                        "刚进入页面时，L1/L2/L3 可能可见但还不能有效使用。请先点击“启动”。",
                        title="先启动",
                    ),
                ],
            },
            {
                "title": "启动实验",
                "blocks": [
                    b(
                        "steps",
                        [
                            "点击页面底部的“启动”。",
                            "等待顶部状态从 idle 变成 connected。",
                            "看到 session 和 epoch 信息后，说明实验环境已经连接。",
                            "黑色终端窗口中出现命令提示符后，就可以输入命令。",
                        ],
                    ),
                    img(
                        "student-02-terminal-connected.png",
                        "点击“启动”后，顶部状态变为 connected，表示终端已连接。",
                    ),
                    b(
                        "table",
                        headers=["状态", "意思", "你应该做什么"],
                        rows=[
                            ["idle", "还没启动", "点击“启动”"],
                            ["provisioning", "正在准备实验", "等待，不要反复点击"],
                            ["connected", "已经连接", "开始输入命令"],
                            ["closed", "连接关闭", "点击“重连”"],
                            ["error", "连接出错", "先重连，仍失败就联系老师"],
                        ],
                    ),
                ],
            },
            {
                "title": "在终端输入命令",
                "blocks": [
                    b(
                        "p",
                        "终端是黑色区域。点击黑色区域后，直接输入命令并按 Enter。",
                    ),
                    img(
                        "student-03-terminal-command.png",
                        "示例：点击黑色终端区域，输入 echo CLA_TERMINAL_READY，然后按 Enter。",
                    ),
                    b(
                        "steps",
                        [
                            "用鼠标点击黑色终端区域。",
                            "输入老师要求的命令，或按题目说明进行操作。",
                            "按 Enter 执行命令。",
                            "根据终端输出继续分析。",
                        ],
                    ),
                    b(
                        "code",
                        "echo CLA_TERMINAL_READY",
                    ),
                    b(
                        "note",
                        "不要在终端里输入或打印自己的密码、token、Cookie、Authorization 等敏感信息。",
                        title="安全提醒",
                    ),
                ],
            },
            {
                "title": "重连和重置怎么选",
                "blocks": [
                    b(
                        "table",
                        headers=["按钮", "什么时候点", "会发生什么"],
                        rows=[
                            ["重连", "页面显示 closed，或网络短暂断开", "保留当前实验，重新连接终端"],
                            ["重置", "环境被自己改坏、无法继续，或老师要求", "重新准备实验环境，可能清空当前状态"],
                        ],
                    ),
                    b(
                        "note",
                        "一般先点“重连”，不要一出问题就点“重置”。重置可能让你丢失当前环境中的操作结果。",
                        title="优先重连",
                    ),
                ],
            },
            {
                "title": "请求提示",
                "blocks": [
                    b(
                        "p",
                        "如果卡住，可以在右侧辅助面板点 L1、L2 或 L3。L1 最轻，L3 更具体。",
                    ),
                    img(
                        "student-04-hint.png",
                        "点击 L1 后，右侧会出现提示卡片，并显示“接受”“稍后”“这不是卡住”“关闭自动提示”。",
                    ),
                    b(
                        "steps",
                        [
                            "点击 L1 获取轻提示。",
                            "如果仍然不知道怎么做，再点击 L2。",
                            "确实长时间无法推进时，再点击 L3。",
                            "提示有帮助就点“接受”。",
                            "暂时不想看就点“稍后”。",
                            "如果系统误判你卡住，点“这不是卡住”。",
                            "不想再自动收到提示，点“关闭自动提示”。",
                        ],
                    ),
                    b(
                        "table",
                        headers=["提示等级", "适合什么时候用"],
                        rows=[
                            ["L1", "不知道下一步方向时"],
                            ["L2", "尝试几次仍然没有进展时"],
                            ["L3", "临近截止或长时间卡住时"],
                        ],
                    ),
                    b(
                        "note",
                        "使用提示不会直接扣总分。页面中的“独立完成指数”会反映你使用提示的情况。",
                        title="提示和成绩",
                    ),
                ],
            },
            {
                "title": "填写答案",
                "blocks": [
                    b(
                        "p",
                        "完成实验后，在右侧“提交”区域填写答案。答案要写你理解到的原因和验证过程，不要只贴一条命令。",
                    ),
                    img(
                        "student-05-answer-filled.png",
                        "在右侧提交框中输入答案。写完后检查一遍，再点击“提交”。",
                    ),
                    b(
                        "steps",
                        [
                            "找到右侧“提交”标题下面的文本框。",
                            "写清楚你发现的问题是什么。",
                            "写清楚你是怎么验证的。",
                            "如果题目要求，补充影响和修复建议。",
                            "确认没有写入密码、token 或不该公开的内容。",
                            "点击蓝色“提交”按钮。",
                        ],
                    ),
                    b(
                        "note",
                        "好答案通常包括：根因、关键现象、验证方式、修复建议。不要只写“完成了”或只贴终端输出。",
                        title="答案建议",
                    ),
                ],
            },
            {
                "title": "提交后看成绩摘要",
                "blocks": [
                    img(
                        "student-06-grade-summary.png",
                        "点击提交后，右侧成绩证据区域会出现 Total 和每个评分项的简要得分。",
                    ),
                    b(
                        "steps",
                        [
                            "点击“提交”后等待几秒。",
                            "查看右侧“成绩证据”。",
                            "先看 Total 总分。",
                            "再看每个评分项的分数。",
                            "点击“完整证据页”查看详细解释。",
                        ],
                    ),
                ],
            },
            {
                "title": "查看完整证据页",
                "blocks": [
                    img(
                        "student-07-grade-evidence.png",
                        "完整证据页左侧是总分和版本信息，中间是每个评分项，右侧是申诉入口。",
                    ),
                    b(
                        "steps",
                        [
                            "点击工作台右侧的“完整证据页”。",
                            "左侧查看总分和独立完成指数。",
                            "中间查看每个评分项。",
                            "点击某个评分项，会在右侧申诉区域同步选择该项。",
                            "阅读评分项下方的解释，判断自己失分原因。",
                        ],
                    ),
                    b(
                        "table",
                        headers=["页面内容", "怎么理解"],
                        rows=[
                            ["总分", "本次提交的总成绩"],
                            ["独立完成指数", "提示使用情况的参考指标，不直接等于分数"],
                            ["Revision", "成绩版本，老师复核后可能变化"],
                            ["评分项", "每一项具体分数和说明"],
                            ["证据标签", "系统记录的评分依据，不需要手动复制"],
                        ],
                    ),
                ],
            },
            {
                "title": "提交申诉",
                "blocks": [
                    b(
                        "p",
                        "如果你认为某一项评分有问题，可以在完整证据页右侧提交申诉。申诉要针对具体评分项，说清楚理由。",
                    ),
                    img(
                        "student-08-appeal-filled.png",
                        "选择评分项，在理由框中写明为什么需要老师复核。",
                    ),
                    b(
                        "steps",
                        [
                            "在右侧“申诉”区域，先选择要申诉的标准。",
                            "在“理由”文本框中写清楚复核原因。",
                            "说明你认为哪个评分项、哪条解释或哪个证据有问题。",
                            "点击“提交申诉”。",
                            "看到 OPEN 和申诉编号后，说明申诉已经提交。",
                        ],
                    ),
                    img(
                        "student-09-appeal-submitted.png",
                        "提交成功后，页面右侧会显示 OPEN、评分项和申诉编号。",
                    ),
                    b(
                        "note",
                        "不要在申诉里写密码、token、Cookie、同学信息或平台内部地址。只写和评分有关的事实。",
                        title="申诉内容",
                    ),
                ],
            },
            {
                "title": "常见问题",
                "blocks": [
                    b(
                        "table",
                        headers=["问题", "先做什么", "还不行怎么办"],
                        rows=[
                            ["点启动后没反应", "等几秒，不要连续点", "刷新页面后重试，仍失败联系老师"],
                            ["状态是 closed", "点击“重连”", "仍失败联系老师"],
                            ["终端没法输入", "先点击黑色终端区域", "刷新页面并重连"],
                            ["不知道下一步", "先点 L1", "再点 L2 或向老师说明已尝试步骤"],
                            ["提交后没有成绩", "等几秒再看右侧成绩证据", "点击完整证据页或联系老师"],
                            ["申诉提交不了", "确认选择了评分项，理由不少于几个字", "刷新成绩页后重试"],
                        ],
                    ),
                ],
            },
            {
                "title": "学生端操作清单",
                "blocks": [
                    b(
                        "checklist",
                        [
                            "我已经进入学生工作台。",
                            "我点击了“启动”，状态变成 connected。",
                            "我在黑色终端里完成了题目要求。",
                            "我需要帮助时按顺序使用了 L1、L2、L3。",
                            "我在提交框中写了根因和验证过程。",
                            "我点击了“提交”。",
                            "我打开“完整证据页”查看了每个评分项。",
                            "如果要申诉，我选择了具体评分项并写清了理由。",
                        ],
                    ),
                ],
            },
        ],
    )


def inline_pdf(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    rendered: list[str] = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            rendered.append(f'<font name="{ACTIVE_PDF_FONT_NAME}">{html.escape(part[1:-1])}</font>')
        else:
            rendered.append(html.escape(part))
    return "".join(rendered)


def render_markdown(manual: Manual) -> str:
    lines = [
        f"# {manual.title}",
        "",
        manual.subtitle,
        "",
        f"- 适用对象：{manual.audience}",
        f"- 生成日期：{GENERATED_AT}",
        "- 项目名称：CyberLab Assistant（CLA）",
        "",
        "## 目录",
        "",
    ]
    for index, section in enumerate(manual.sections, start=1):
        lines.append(f"{index}. [{section['title']}](#{slug(section['title'])})")
    lines.append("")
    for index, section in enumerate(manual.sections, start=1):
        lines.extend([f'<a id="{slug(section["title"])}"></a>', f"## {index}. {section['title']}", ""])
        for item in section["blocks"]:
            kind = item["kind"]
            if kind == "p":
                lines.extend([item["content"], ""])
            elif kind == "note":
                lines.extend([f"> **{item['title']}**：{item['content']}", ""])
            elif kind in {"bullets", "checklist"}:
                mark = "- [ ]" if kind == "checklist" else "-"
                for text in item["content"]:
                    lines.append(f"{mark} {text}")
                lines.append("")
            elif kind == "steps":
                for step_index, text in enumerate(item["content"], start=1):
                    lines.append(f"{step_index}. {text}")
                lines.append("")
            elif kind == "code":
                lines.extend(["```text", item["content"].strip("\n"), "```", ""])
            elif kind == "image":
                lines.extend([f"![{item['caption']}](assets/{item['content']})", "", f"*{item['caption']}*", ""])
            elif kind == "table":
                headers = item["headers"]
                lines.append("| " + " | ".join(headers) + " |")
                lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for row in item["rows"]:
                    lines.append("| " + " | ".join(str(cell).replace("\n", "<br>") for cell in row) + " |")
                lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(manual: Manual) -> str:
    nav = "\n".join(
        f'<a href="#{slug(section["title"])}">{index}. {html.escape(section["title"])}</a>'
        for index, section in enumerate(manual.sections, start=1)
    )
    body_parts: list[str] = []
    for index, section in enumerate(manual.sections, start=1):
        body_parts.append(f'<section id="{slug(section["title"])}"><h2>{index}. {html.escape(section["title"])}</h2>')
        for item in section["blocks"]:
            body_parts.append(render_html_block(item))
        body_parts.append("</section>")
    body = "\n".join(body_parts)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(manual.title)}</title>
<style>
:root {{
  --bg: #f7f8fb;
  --panel: #ffffff;
  --text: #172033;
  --muted: #637083;
  --line: #d9e0ea;
  --brand: #117394;
  --note: #eef7fb;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
  line-height: 1.72;
}}
.layout {{
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  min-height: 100vh;
}}
aside {{
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  background: var(--panel);
  border-right: 1px solid var(--line);
  padding: 22px 18px;
}}
aside h1 {{ font-size: 17px; line-height: 1.35; margin: 0 0 8px; }}
aside p {{ color: var(--muted); font-size: 12px; margin: 0 0 18px; }}
nav a {{
  display: block;
  color: var(--muted);
  text-decoration: none;
  padding: 6px 8px;
  border-radius: 7px;
  font-size: 12px;
}}
nav a:hover {{ color: var(--brand); background: #edf5f8; }}
main {{
  max-width: 1120px;
  width: 100%;
  margin: 0 auto;
  padding: 40px 34px 80px;
}}
header {{
  border-bottom: 1px solid var(--line);
  margin-bottom: 26px;
  padding-bottom: 22px;
}}
header h1 {{ font-size: 34px; line-height: 1.2; margin: 0 0 10px; }}
header p {{ color: var(--muted); margin: 4px 0; }}
section {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 22px;
  margin: 18px 0;
}}
h2 {{ font-size: 22px; margin: 0 0 12px; color: #0b4f69; }}
.note {{
  border-left: 4px solid var(--brand);
  background: var(--note);
  padding: 12px 14px;
  margin: 14px 0;
}}
.note strong {{ display: block; margin-bottom: 4px; }}
figure {{ margin: 16px 0; }}
figure img {{
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
figcaption {{ color: var(--muted); font-size: 13px; margin-top: 6px; }}
table {{ width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 13px; }}
th, td {{ border: 1px solid var(--line); padding: 8px 9px; vertical-align: top; }}
th {{ background: #edf2f8; }}
code {{ font-family: "SFMono-Regular", Consolas, monospace; color: #0b4f69; }}
pre {{
  background: #0b1220;
  color: #edf4ff;
  padding: 14px;
  overflow: auto;
  border-radius: 7px;
  font-size: 12px;
  line-height: 1.55;
}}
@media (max-width: 860px) {{
  .layout {{ display: block; }}
  aside {{ position: static; height: auto; }}
  main {{ padding: 24px 16px 60px; }}
}}
@media print {{
  body {{ background: white; }}
  aside {{ display: none; }}
  .layout {{ display: block; }}
  main {{ max-width: none; padding: 0; }}
  section {{ break-inside: avoid; border-color: #ddd; }}
  figure {{ break-inside: avoid; }}
}}
</style>
</head>
<body>
<div class="layout">
<aside>
<h1>{html.escape(manual.title)}</h1>
<p>{html.escape(manual.subtitle)}<br>生成日期：{GENERATED_AT}</p>
<nav>
{nav}
</nav>
</aside>
<main>
<header>
<h1>{html.escape(manual.title)}</h1>
<p>{html.escape(manual.subtitle)}</p>
<p>适用对象：{html.escape(manual.audience)} · 生成日期：{GENERATED_AT}</p>
</header>
{body}
</main>
</div>
</body>
</html>
"""


def render_html_block(item: dict[str, Any]) -> str:
    kind = item["kind"]
    if kind == "p":
        return f"<p>{html.escape(item['content'])}</p>"
    if kind == "note":
        return f"<div class=\"note\"><strong>{html.escape(item['title'])}</strong>{html.escape(item['content'])}</div>"
    if kind in {"bullets", "checklist"}:
        items = "\n".join(f"<li>{html.escape(text)}</li>" for text in item["content"])
        return f"<ul>{items}</ul>"
    if kind == "steps":
        items = "\n".join(f"<li>{html.escape(text)}</li>" for text in item["content"])
        return f"<ol>{items}</ol>"
    if kind == "code":
        return f"<pre><code>{html.escape(item['content'].strip())}</code></pre>"
    if kind == "image":
        return (
            f'<figure><img src="assets/{html.escape(item["content"])}" '
            f'alt="{html.escape(item["caption"])}"><figcaption>{html.escape(item["caption"])}</figcaption></figure>'
        )
    if kind == "table":
        headers = "".join(f"<th>{html.escape(str(header))}</th>" for header in item["headers"])
        rows = []
        for row in item["rows"]:
            cells = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
            rows.append(f"<tr>{cells}</tr>")
        return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    raise ValueError(f"unknown block kind: {kind}")


def build_pdf(manual: Manual) -> None:
    register_pdf_font()
    output = PDF_DIR / manual.pdf_name
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=manual.title,
        author="CyberLab Assistant（CLA）",
    )
    width = A4[0] - doc.leftMargin - doc.rightMargin
    styles = pdf_styles()
    story: list[Any] = [
        Spacer(1, 32 * mm),
        Paragraph(manual.title, styles["cover"]),
        Spacer(1, 8 * mm),
        Paragraph(manual.subtitle, styles["subtitle"]),
        Spacer(1, 8 * mm),
        Paragraph(f"适用对象：{manual.audience}", styles["meta"]),
        Paragraph(f"生成日期：{GENERATED_AT}", styles["meta"]),
        Paragraph("项目名称：CyberLab Assistant（CLA）", styles["meta"]),
        PageBreak(),
        Paragraph("目录", styles["h1"]),
    ]
    for index, section in enumerate(manual.sections, start=1):
        story.append(Paragraph(f"{index}. {inline_pdf(section['title'])}", styles["toc"]))
    story.append(PageBreak())

    for index, section in enumerate(manual.sections, start=1):
        if section["title"] in {"教师端常见问题", "常见问题", "学生端操作清单"}:
            story.append(PageBreak())
        story.append(Paragraph(f"{index}. {inline_pdf(section['title'])}", styles["h1"]))
        story.append(Spacer(1, 2 * mm))
        for item in section["blocks"]:
            add_pdf_block(story, item, styles, width)
        story.append(Spacer(1, 4 * mm))

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = ACTIVE_PDF_FONT_NAME
    return {
        "cover": ParagraphStyle(
            "cover",
            fontName=base,
            fontSize=21,
            leading=29,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#172033"),
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=base,
            fontSize=12.5,
            leading=19,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#4c5b70"),
        ),
        "meta": ParagraphStyle(
            "meta",
            fontName=base,
            fontSize=10,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#637083"),
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName=base,
            fontSize=15,
            leading=21,
            textColor=colors.HexColor("#0b4f69"),
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=base,
            fontSize=9.2,
            leading=14,
            textColor=colors.HexColor("#172033"),
            spaceAfter=5,
        ),
        "note": ParagraphStyle(
            "note",
            fontName=base,
            fontSize=9,
            leading=13.5,
            textColor=colors.HexColor("#172033"),
            leftIndent=8,
            rightIndent=8,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "toc": ParagraphStyle(
            "toc",
            fontName=base,
            fontSize=10.5,
            leading=16,
            textColor=colors.HexColor("#172033"),
        ),
        "table": ParagraphStyle(
            "table",
            fontName=base,
            fontSize=8.0,
            leading=11,
            textColor=colors.HexColor("#172033"),
        ),
        "caption": ParagraphStyle(
            "caption",
            fontName=base,
            fontSize=8.2,
            leading=11,
            textColor=colors.HexColor("#637083"),
            spaceAfter=6,
        ),
        "code": ParagraphStyle(
            "code",
            fontName=base,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#0b1220"),
            leftIndent=4,
            rightIndent=4,
        ),
    }


def add_pdf_block(story: list[Any], item: dict[str, Any], styles: dict[str, ParagraphStyle], width: float) -> None:
    kind = item["kind"]
    if kind == "p":
        story.append(Paragraph(inline_pdf(item["content"]), styles["body"]))
    elif kind == "note":
        text = f"<b>{inline_pdf(item['title'])}</b>：{inline_pdf(item['content'])}"
        table = Table([[Paragraph(text, styles["note"])]], colWidths=[width])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef7fb")),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#117394")),
                    ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e0ea")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 3 * mm))
    elif kind in {"bullets", "checklist"}:
        for text in item["content"]:
            prefix = "□" if kind == "checklist" else "•"
            story.append(Paragraph(f"{prefix} {inline_pdf(text)}", styles["body"]))
        story.append(Spacer(1, 2 * mm))
    elif kind == "steps":
        for index, text in enumerate(item["content"], start=1):
            story.append(Paragraph(f"{index}. {inline_pdf(text)}", styles["body"]))
        story.append(Spacer(1, 2 * mm))
    elif kind == "code":
        story.append(Preformatted(item["content"].strip("\n"), styles["code"], maxLineLength=92))
        story.append(Spacer(1, 3 * mm))
    elif kind == "image":
        add_pdf_image(story, item["content"], item["caption"], styles, width)
    elif kind == "table":
        rows = [[Paragraph(inline_pdf(str(cell)), styles["table"]) for cell in item["headers"]]]
        for row in item["rows"]:
            rows.append([Paragraph(inline_pdf(str(cell)), styles["table"]) for cell in row])
        col_count = len(item["headers"])
        table = Table(rows, colWidths=[width / col_count] * col_count, repeatRows=1, splitByRow=0)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f8")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e0ea")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 4 * mm))
    else:
        raise ValueError(f"unknown block kind: {kind}")


def add_pdf_image(
    story: list[Any],
    file_name: str,
    caption: str,
    styles: dict[str, ParagraphStyle],
    width: float,
) -> None:
    image_path = ASSET_DIR / file_name
    if not image_path.exists():
        story.append(Paragraph(f"截图缺失：{inline_pdf(file_name)}", styles["note"]))
        return
    reader = ImageReader(str(image_path))
    image_width, image_height = reader.getSize()
    max_width = width
    max_height = 125 * mm
    scale = min(max_width / image_width, max_height / image_height)
    rendered = RLImage(str(image_path), width=image_width * scale, height=image_height * scale)
    story.append(rendered)
    story.append(Paragraph(inline_pdf(caption), styles["caption"]))
    story.append(Spacer(1, 2 * mm))


def draw_footer(canvas: Any, doc: SimpleDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont(ACTIVE_PDF_FONT_NAME, 8)
    canvas.setFillColor(colors.HexColor("#637083"))
    canvas.drawString(16 * mm, 9 * mm, "CyberLab Assistant（CLA）用户手册")
    canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def slug(value: str) -> str:
    normalized = re.sub(r"\s+", "-", value.strip().lower())
    normalized = re.sub(r"[^\w\-\u4e00-\u9fff]", "", normalized)
    return normalized


def register_pdf_font() -> None:
    global ACTIVE_PDF_FONT_NAME
    if ACTIVE_PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    for candidate in PDF_FONT_CANDIDATES:
        if candidate.exists() and candidate.suffix.lower() == ".ttf":
            pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(candidate)))
            ACTIVE_PDF_FONT_NAME = PDF_FONT_NAME
            return
    pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT_FALLBACK))
    ACTIVE_PDF_FONT_NAME = PDF_FONT_FALLBACK


def write_manual(manual: Manual) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    (DOC_DIR / f"{manual.slug}.md").write_text(render_markdown(manual), encoding="utf-8")
    (DOC_DIR / f"{manual.slug}.html").write_text(render_html(manual), encoding="utf-8")
    build_pdf(manual)


def main() -> None:
    for manual in (teacher_manual(), student_manual()):
        write_manual(manual)
        print(
            f"generated {manual.slug}: docs/user-manuals/{manual.slug}.md, "
            f"docs/user-manuals/{manual.slug}.html, output/pdf/{manual.pdf_name}"
        )


if __name__ == "__main__":
    main()
