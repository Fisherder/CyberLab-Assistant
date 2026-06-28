import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const outDir = mkdtempSync(join(tmpdir(), "cla-authoring-agent-"));
const require = createRequire(import.meta.url);
const ts = require("typescript");
const sourcePath = join(root, "lib/authoringFieldUpdates.ts");
const compiled = ts.transpileModule(readFileSync(sourcePath, "utf8"), {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    esModuleInterop: true
  }
});
writeFileSync(join(outDir, "authoringFieldUpdates.js"), compiled.outputText);

const {
  inferAuthoringFieldUpdate,
  applyPreviewFieldUpdate
} = require(join(outDir, "authoringFieldUpdates.js"));

const basePreview = {
  courseId: "course_websec",
  challengeVersionId: "cv_web_sqli_auth_1_3_0",
  title: "SQL 注入认证绕过实践",
  summary: "通过终端访问目标 Web 服务，观察登录接口在异常输入下的认证边界。",
  description:
    "进入题目后先获取容器环境，再打开题目给出的目标地址，围绕登录接口构造请求。",
  requirements:
    "提交根因解释、验证过程和修复建议。",
  tags: "Web安全, SQL注入, 认证, 终端实践"
};

const baseWindow = {
  openAt: "2026-06-29T09:00",
  dueAt: "2026-06-29T11:00",
  mode: "duration"
};

const baseIntent = {
  category: "WEB",
  target: "SQLI",
  difficulty: 3,
  expectedMinutes: 90,
  workspaceType: "TERMINAL",
  isolationTier: 1,
  allowedTools: ["curl", "python"],
  learningObjectives: ["identify-input-trust-boundary"]
};

const now = new Date("2026-06-29T09:00:00+08:00");

const cases = [
  ...[
    ["时间截止到下周", (r) => dueStarts(r, "2026-07-06")],
    ["下周截止吧", (r) => dueStarts(r, "2026-07-06")],
    ["结束时间改到下周五18点", (r) => dueStarts(r, "2026-07-03T18:00")],
    ["截止日期设为明天晚上", (r) => dueStarts(r, "2026-06-30")],
    ["今天 23:59 截止", (r) => dueStarts(r, "2026-06-29T23:59")],
    ["7月5日截止", (r) => dueStarts(r, "2026-07-05")],
    ["2026-07-10 截止", (r) => dueStarts(r, "2026-07-10")],
    ["开放时间持续一年", (r) => dueStarts(r, "2027-06-29")],
    ["发布持续半年", (r) => dueStarts(r, "2026-12-29")],
    ["持续三个月", (r) => dueStarts(r, "2026-09-29")],
    ["持续两周", (r) => dueStarts(r, "2026-07-13")],
    ["持续十天", (r) => dueStarts(r, "2026-07-09")],
    ["持续4小时", (r) => dueStarts(r, "2026-06-29T13:00")],
    ["开始时间改成明天9点，结束时间改成下周五18点", (r) => openStarts(r, "2026-06-30T09:00") && dueStarts(r, "2026-07-03T18:00")],
    ["改到下个月开始", (r) => openStarts(r, "2026-07-29")],
    ["下下个月开始", (r) => openStarts(r, "2026-08-29")],
    ["本月月底截止", (r) => dueStarts(r, "2026-06-30")],
    ["下下周截止", (r) => dueStarts(r, "2026-07-13")],
    ["发布从后天开始", (r) => openStarts(r, "2026-07-01")],
    ["今晚截止", (r) => dueStarts(r, "2026-06-29")]
  ],
  ...[
    ["标题改成 Web 安全综合实践", (r) => preview(r).title === "Web 安全综合实践"],
    ["题目标题设置为 SQL 注入专项训练", (r) => preview(r).title === "SQL 注入专项训练"],
    ["题名改为 认证绕过强化练习", (r) => preview(r).title === "认证绕过强化练习"],
    ["名称叫做 输入边界验证实验", (r) => preview(r).title === "输入边界验证实验"],
    ["课程 ID 改成 course_advanced_web", (r) => preview(r).courseId === "course_advanced_web"],
    ["课程ID设为 course_pwn_2026", (r) => preview(r).courseId === "course_pwn_2026"],
    ["题目版本 ID 改成 cv_web_sqli_2_0_0", (r) => preview(r).challengeVersionId === "cv_web_sqli_2_0_0"],
    ["版本ID设为 cv_mix_001", (r) => preview(r).challengeVersionId === "cv_mix_001"],
    ["摘要改成 面向登录认证边界的综合练习", (r) => preview(r).summary === "面向登录认证边界的综合练习"],
    ["列表摘要设置为 学生需要验证输入边界", (r) => preview(r).summary === "学生需要验证输入边界"],
    ["题目说明改成 先观察页面，再验证接口。", (r) => preview(r).description === "先观察页面，再验证接口"],
    ["题面设置为 需要围绕登录接口完成验证。", (r) => preview(r).description === "需要围绕登录接口完成验证"],
    ["完成要求改成 提交验证截图和修复建议", (r) => preview(r).requirements === "提交验证截图和修复建议"],
    ["提交要求设置为 写清楚 payload、证据和修复方式", (r) => preview(r).requirements.includes("payload")],
    ["标签改成 Web安全, SQL注入, 期末考核", (r) => preview(r).tags.includes("期末考核")],
    ["标签设置为 Pwn、整数溢出、终端实践", (r) => preview(r).tags.includes("整数溢出")],
    ["标签增加 审计", (r) => preview(r).tags.includes("审计")],
    ["添加标签 课程考核", (r) => preview(r).tags.includes("课程考核")],
    ["加上 Web复现 标签", (r) => preview(r).tags.includes("Web复现")],
    ["标签移除 认证", (r) => !preview(r).tags.includes("认证")],
    ["去掉 SQL注入 标签", (r) => !preview(r).tags.includes("SQL注入")],
    ["完成要求增加 不允许使用自动扫描器", (r) => preview(r).requirements.includes("自动扫描器")],
    ["题目说明补充 目标地址会在题目页面显示", (r) => preview(r).description.includes("目标地址")],
    ["摘要增加 适合课堂演示", (r) => preview(r).summary.includes("课堂演示")]
  ],
  ...[
    ["题目改得更正式一些", (r) => preview(r).requirements.includes("规范表述")],
    ["题面写得更严谨", (r) => hasLabel(r, "正式")],
    ["描述更专业一点", (r) => hasLabel(r, "正式")],
    ["题目改得更详细", (r) => preview(r).description.includes("期望观察点")],
    ["说明多一点", (r) => preview(r).description.includes("期望观察点")],
    ["再展开一下题面", (r) => preview(r).description.includes("期望观察点")],
    ["适合新手一点", (r) => preview(r).summary.includes("基础验证") || r.constraints.difficulty === 1],
    ["降低门槛", (r) => preview(r).summary.includes("基础验证")],
    ["加上安全提示，不要泄露 token", (r) => preview(r).requirements.includes("敏感信息")],
    ["注意事项里补充 Cookie 和 Authorization 不要提交", (r) => preview(r).requirements.includes("Authorization")],
    ["至少要有一个GUI页面", (r) => preview(r).description.includes("GUI 页面") && preview(r).tags.includes("GUI页面")],
    ["加一个浏览器页面", (r) => preview(r).description.includes("浏览器访问")],
    ["要有前端页面可以点", (r) => preview(r).description.includes("浏览器访问")],
    ["目标服务提供图形页面", (r) => preview(r).requirements.includes("GUI 页面")],
    ["再组合点其他题目", (r) => r.constraints.preferComposition === true && preview(r).tags.includes("组合题")],
    ["组合一些别的知识点", (r) => r.constraints.preferComposition === true],
    ["做成多知识点综合题", (r) => r.constraints.preferComposition === true],
    ["从零写一个定制靶场", (r) => r.constraints.preferCustomGeneration === true],
    ["不要题库，现场编写环境", (r) => r.constraints.preferCustomGeneration === true],
    ["保留终端实践", (r) => r.constraints.workspaceType === "TERMINAL"],
    ["需要远程桌面 GUI工具", (r) => r.constraints.workspaceType === "REMOTE_DESKTOP"]
  ],
  ...[
    ["难度加大一些", (r) => r.constraints.difficulty === 4],
    ["难度提高一点", (r) => r.constraints.difficulty === 4],
    ["题目更难一点", (r) => r.constraints.difficulty === 4],
    ["把难度上调", (r) => r.constraints.difficulty === 4],
    ["难度降低一点", (r) => r.constraints.difficulty === 2],
    ["题目简单一点", (r) => r.constraints.difficulty === 1],
    ["难度改成入门", (r) => r.constraints.difficulty === 1],
    ["难度设为基础", (r) => r.constraints.difficulty === 2],
    ["难度设置为中等", (r) => r.constraints.difficulty === 3],
    ["难度改为较难", (r) => r.constraints.difficulty === 4],
    ["难度改成高难", (r) => r.constraints.difficulty === 5],
    ["做成非常难", (r) => r.constraints.difficulty === 5],
    ["难度 1 级", (r) => r.constraints.difficulty === 1],
    ["难度设置为5星", (r) => r.constraints.difficulty === 5],
    ["预计 30 分钟完成", (r) => r.constraints.expectedMinutes === 30],
    ["解题时间控制在45分钟", (r) => r.constraints.expectedMinutes === 45],
    ["预计耗时2小时", (r) => r.constraints.expectedMinutes === 120],
    ["完成时长 90 分钟", (r) => r.constraints.expectedMinutes === 90],
    ["学生预计 1 小时", (r) => r.constraints.expectedMinutes === 60],
    ["控制时间 3小时", (r) => r.constraints.expectedMinutes === 180]
  ],
  ...[
    ["下周一开始，持续两周", (r) => openStarts(r, "2026-07-06") && dueStarts(r, "2026-07-20")],
    ["发布从明天9点开始，开放4小时", (r) => openStarts(r, "2026-06-30T09:00") && dueStarts(r, "2026-06-30T13:00")],
    ["开始时间设为7月1日，截止到7月10日", (r) => openStarts(r, "2026-07-01") && dueStarts(r, "2026-07-10")],
    ["从下个月开始，持续一个月", (r) => openStarts(r, "2026-07-29") && dueStarts(r, "2026-08-29")],
    ["明天开始，下周截止", (r) => openStarts(r, "2026-06-30") && dueStarts(r, "2026-07-06")],
    ["今天开始，三天后截止", (r) => openStarts(r, "2026-06-29") && dueStarts(r, "2026-07-02")],
    ["开放一周", (r) => dueStarts(r, "2026-07-06")],
    ["时间给两个月", (r) => dueStarts(r, "2026-08-29")],
    ["截止到后天", (r) => dueStarts(r, "2026-07-01")],
    ["下周三 10:30 结束", (r) => dueStarts(r, "2026-07-01T10:30")]
  ],
  ...[
    ["标题改成 SQLi Final Lab，同时标签增加 期末", (r) => preview(r).title === "SQLi Final Lab，同时标签增加 期末"],
    ["说明增加 学生先访问 /healthz", (r) => preview(r).description.includes("/healthz")],
    ["要求补充 不能提交真实账号", (r) => preview(r).requirements.includes("真实账号")],
    ["摘要设置为 一道综合 Web 安全练习", (r) => preview(r).summary.includes("综合 Web")],
    ["标签增加 课堂练习、可复现", (r) => preview(r).tags.includes("课堂练习") && preview(r).tags.includes("可复现")],
    ["标签删除 终端实践", (r) => !preview(r).tags.includes("终端实践")],
    ["题目名称改为 认证逻辑专项", (r) => preview(r).title === "认证逻辑专项"],
    ["名字叫 期中 Web 训练", (r) => preview(r).title === "期中 Web 训练"],
    ["验收要求设置为 必须解释根因", (r) => preview(r).requirements.includes("根因")],
    ["题面补充 目标页面包含登录表单", (r) => preview(r).description.includes("登录表单")]
  ]
];

let passed = 0;
const failures = [];
for (const [text, assertCase] of cases) {
  const result = inferAuthoringFieldUpdate(text, basePreview, baseWindow, now, baseIntent);
  try {
    if (!result.hasChanges) {
      throw new Error("没有产生任何状态更新");
    }
    if (!assertCase(result)) {
      throw new Error("断言未通过");
    }
    passed += 1;
  } catch (error) {
    failures.push({ text, error: error.message, result });
  }
}

if (failures.length) {
  console.error(JSON.stringify({ passed, failed: failures.length, failures }, null, 2));
  process.exit(1);
}

const sequenceFailures = [];
const sequenceResults = runSequences();
for (const result of sequenceResults) {
  if (!result.ok) sequenceFailures.push(result);
}

if (sequenceFailures.length) {
  console.error(JSON.stringify({ passed, failedSequences: sequenceFailures.length, sequenceFailures }, null, 2));
  process.exit(1);
}

console.log(`作者 Agent 自由指令测试通过：${passed} / ${cases.length}，多轮序列 ${sequenceResults.length} / ${sequenceResults.length}`);

function preview(result) {
  return applyPreviewFieldUpdate(basePreview, result.preview);
}

function dueStarts(result, prefix) {
  return Boolean(result.publish?.window.dueAt.startsWith(prefix));
}

function openStarts(result, prefix) {
  return Boolean(result.publish?.window.openAt.startsWith(prefix));
}

function hasLabel(result, value) {
  return result.labels.some((label) => label.includes(value));
}

function runSequences() {
  const sequences = [
    {
      name: "正式 SQLi 下月 GUI 高难",
      turns: ["创建一个中等难度 SQL 注入题目", "改到下个月开始", "题目改得更正式一些", "至少要有一个GUI页面", "难度加大一些"],
      assert: (state) =>
        state.window.openAt.startsWith("2026-07-29") &&
        state.preview.requirements.includes("规范表述") &&
        state.preview.description.includes("GUI 页面") &&
        state.intent.difficulty === 4
    },
    {
      name: "标题标签要求连续修改",
      turns: ["标题改成 Web 综合安全训练", "标签增加 期末考核", "完成要求增加 不允许使用自动扫描器", "标签移除 认证"],
      assert: (state) =>
        state.preview.title === "Web 综合安全训练" &&
        state.preview.tags.includes("期末考核") &&
        !state.preview.tags.includes("认证") &&
        state.preview.requirements.includes("自动扫描器")
    },
    {
      name: "开始截止预计时长",
      turns: ["开始时间改成明天9点，结束时间改成下周五18点", "预计 45 分钟完成"],
      assert: (state) =>
        state.window.openAt.startsWith("2026-06-30T09:00") &&
        state.window.dueAt.startsWith("2026-07-03T18:00") &&
        state.intent.expectedMinutes === 45
    },
    {
      name: "组合题再定制",
      turns: ["再组合点其他题目", "从零写一个定制靶场", "题目说明补充 需要包含两个知识点"],
      assert: (state) =>
        state.constraints.preferComposition === true &&
        state.constraints.preferCustomGeneration === true &&
        state.preview.tags.includes("组合题") &&
        state.preview.description.includes("两个知识点")
    },
    {
      name: "难度上下调保持边界",
      turns: ["难度改成高难", "难度降低一点", "难度加大一些", "题目改得更详细"],
      assert: (state) => state.intent.difficulty === 5 && state.preview.description.includes("期望观察点")
    },
    {
      name: "远程桌面再回终端",
      turns: ["需要远程桌面 GUI工具", "还是保持终端实践", "加上安全提示，不要泄露 token"],
      assert: (state) =>
        state.intent.workspaceType === "TERMINAL" &&
        state.preview.requirements.includes("敏感信息")
    },
    {
      name: "下周截止再持续延期",
      turns: ["时间截止到下周", "开放时间持续两周", "发布从后天开始"],
      assert: (state) =>
        state.window.openAt.startsWith("2026-07-01") &&
        state.window.dueAt.startsWith("2026-07-15")
    },
    {
      name: "课程版本摘要说明要求",
      turns: [
        "课程 ID 改成 course_enterprise_web",
        "版本ID设为 cv_enterprise_web_01",
        "摘要改成 企业 Web 安全实践",
        "说明增加 目标地址由页面提供",
        "要求补充 提交修复建议"
      ],
      assert: (state) =>
        state.preview.courseId === "course_enterprise_web" &&
        state.preview.challengeVersionId === "cv_enterprise_web_01" &&
        state.preview.summary === "企业 Web 安全实践" &&
        state.preview.description.includes("目标地址") &&
        state.preview.requirements.includes("修复建议")
    },
    {
      name: "新手题再提升",
      turns: ["适合新手一点", "难度加大一些", "题目说明补充 给出健康检查入口"],
      assert: (state) =>
        state.preview.summary.includes("基础验证") &&
        state.intent.difficulty === 2 &&
        state.preview.description.includes("健康检查")
    },
    {
      name: "GUI 页面组合综合题",
      turns: ["至少要有一个GUI页面", "组合一些别的知识点", "完成要求增加 必须访问 GUI 页面并记录响应"],
      assert: (state) =>
        state.preview.tags.includes("GUI页面") &&
        state.preview.tags.includes("组合题") &&
        state.constraints.preferComposition === true &&
        state.preview.requirements.includes("记录响应")
    },
    {
      name: "显式时间覆盖持续时间",
      turns: ["持续三个月", "截止到7月10日", "开始时间设为7月1日"],
      assert: (state) =>
        state.window.openAt.startsWith("2026-07-01") &&
        state.window.dueAt.startsWith("2026-07-10")
    },
    {
      name: "正式化不覆盖标题显式修改",
      turns: ["标题改成 认证逻辑专项", "题目改得更正式一些", "标签增加 审计"],
      assert: (state) =>
        state.preview.title === "认证逻辑专项" &&
        state.preview.requirements.includes("规范表述") &&
        state.preview.tags.includes("审计")
    }
  ];

  return sequences.map((sequence) => {
    const state = {
      preview: { ...basePreview },
      window: { ...baseWindow },
      intent: { ...baseIntent },
      constraints: {}
    };
    const turns = [];
    for (const text of sequence.turns) {
      const result = inferAuthoringFieldUpdate(text, state.preview, state.window, now, state.intent);
      state.preview = applyPreviewFieldUpdate(state.preview, result.preview);
      if (result.publish) state.window = result.publish.window;
      state.constraints = { ...state.constraints, ...result.constraints };
      state.intent = {
        ...state.intent,
        ...pickIntentPatch(result.constraints)
      };
      turns.push({ text, labels: result.labels, constraints: result.constraints });
    }
    return {
      name: sequence.name,
      ok: sequence.assert(state),
      finalState: state,
      turns
    };
  });
}

function pickIntentPatch(constraints) {
  const patch = {};
  for (const key of ["category", "target", "difficulty", "expectedMinutes", "workspaceType", "isolationTier"]) {
    if (constraints[key] !== undefined) patch[key] = constraints[key];
  }
  return patch;
}
