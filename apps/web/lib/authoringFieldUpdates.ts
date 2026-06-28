export type AuthoringPreviewState = {
  courseId: string;
  challengeVersionId: string;
  title: string;
  summary: string;
  description: string;
  requirements: string;
  tags: string;
};

export type PublishWindow = {
  openAt: string;
  dueAt: string;
  mode?: "duration" | "explicit";
};

export type PublishWindowUpdate = {
  window: PublishWindow;
  label: string;
  labels: string[];
};

export type AuthoringCourseIntentState = {
  category?: string;
  target?: string;
  difficulty?: number;
  expectedMinutes?: number;
  workspaceType?: string;
  isolationTier?: number;
  allowedTools?: string[];
  learningObjectives?: string[];
};

export type PreviewFieldUpdate = {
  patch: Partial<AuthoringPreviewState>;
  append: Partial<Pick<AuthoringPreviewState, "summary" | "description" | "requirements">>;
  addTags: string[];
  removeTags: string[];
  labels: string[];
};

export type AuthoringFieldUpdate = {
  preview: PreviewFieldUpdate;
  publish: PublishWindowUpdate | null;
  constraints: Record<string, unknown>;
  labels: string[];
  hasChanges: boolean;
};

type DurationUnit = "year" | "month" | "week" | "day" | "hour";

const TEXT_FIELDS = ["summary", "description", "requirements"] as const;

export function inferAuthoringFieldUpdate(
  text: string,
  currentPreview: AuthoringPreviewState,
  currentPublishWindow: PublishWindow,
  now = new Date(),
  currentIntent: AuthoringCourseIntentState | null = null
): AuthoringFieldUpdate {
  const preview = inferPreviewFieldUpdate(text, currentPreview);
  const freeformPreview = inferFreeformPreviewUpdate(text, currentPreview);
  mergePreviewUpdate(preview, freeformPreview);
  const publish = inferPublishWindowUpdate(text, currentPublishWindow, now);
  const intent = inferIntentUpdate(text, currentIntent);
  const labels = [...preview.labels, ...(publish?.labels ?? []), ...intent.labels];
  return {
    preview,
    publish,
    constraints: intent.constraints,
    labels,
    hasChanges: labels.length > 0
  };
}

export function applyPreviewFieldUpdate(
  base: AuthoringPreviewState,
  update: PreviewFieldUpdate
): AuthoringPreviewState {
  let next: AuthoringPreviewState = { ...base, ...update.patch };
  for (const field of TEXT_FIELDS) {
    const addition = update.append[field];
    if (addition) {
      const current = next[field].trim();
      next = { ...next, [field]: current ? `${current}\n${addition}` : addition };
    }
  }
  if (update.addTags.length || update.removeTags.length) {
    const remove = new Set(update.removeTags.map((tag) => tag.toLowerCase()));
    const tags = normalizeTags(next.tags).filter((tag) => !remove.has(tag.toLowerCase()));
    for (const tag of update.addTags) {
      if (!tags.some((item) => item.toLowerCase() === tag.toLowerCase())) {
        tags.push(tag);
      }
    }
    next = { ...next, tags: tags.join(", ") };
  }
  return next;
}

export function emptyPreviewFieldUpdate(): PreviewFieldUpdate {
  return {
    patch: {},
    append: {},
    addTags: [],
    removeTags: [],
    labels: []
  };
}

function mergePreviewUpdate(target: PreviewFieldUpdate, source: PreviewFieldUpdate) {
  target.patch = { ...target.patch, ...source.patch };
  for (const field of TEXT_FIELDS) {
    const nextValue = source.append[field];
    if (!nextValue) continue;
    const currentValue = target.append[field];
    target.append[field] = currentValue ? `${currentValue}\n${nextValue}` : nextValue;
  }
  target.addTags.push(...source.addTags);
  target.removeTags.push(...source.removeTags);
  target.labels.push(...source.labels);
}

export function toLocalInput(value: string | Date | null): string {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export function localInputToDate(value: string | null | undefined, fallback: Date): Date {
  if (!value) return new Date(fallback.getTime());
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return new Date(fallback.getTime());
  return parsed;
}

export function formatLocalDateTime(value: string): string {
  return value.replace("T", " ");
}

function inferPreviewFieldUpdate(text: string, current: AuthoringPreviewState): PreviewFieldUpdate {
  const update = emptyPreviewFieldUpdate();

  setPatch(update, "courseId", extractValue(text, ["课程 ID", "课程ID", "course id"], true), "课程 ID");
  setPatch(
    update,
    "challengeVersionId",
    extractValue(text, ["题目版本 ID", "题目版本ID", "版本 ID", "版本ID", "challenge version id", "challengeVersionId"], true),
    "题目版本 ID"
  );
  setPatch(update, "title", extractValue(text, ["题目标题", "标题", "题名", "名称", "名字"], false), "题目标题");
  setPatch(update, "summary", extractValue(text, ["列表摘要", "摘要", "简介"], false), "列表摘要");
  setPatch(update, "description", extractValue(text, ["题目说明", "说明", "描述", "题面"], false), "题目说明");
  setPatch(update, "requirements", extractValue(text, ["完成要求", "提交要求", "验收要求", "要求"], false), "完成要求");

  const tagReplacement = extractValue(text, ["标签"], false);
  if (tagReplacement && /标签/.test(text)) {
    const tags = normalizeTags(tagReplacement);
    if (tags.length) {
      update.patch.tags = tags.join(", ");
      update.labels.push(`标签已更新为 ${tags.join("、")}`);
    }
  }

  const addedTags = extractTagList(text, ["添加", "增加", "加上", "加入", "补充"]);
  if (addedTags.length) {
    update.addTags.push(...addedTags);
    update.labels.push(`标签已增加 ${addedTags.join("、")}`);
  }

  const removedTags = extractTagList(text, ["删除", "移除", "去掉", "去除"]);
  if (removedTags.length) {
    update.removeTags.push(...removedTags);
    update.labels.push(`标签已移除 ${removedTags.join("、")}`);
  }

  appendField(update, "summary", extractAppendValue(text, ["列表摘要", "摘要", "简介"]), "列表摘要");
  appendField(update, "description", extractAppendValue(text, ["题目说明", "说明", "描述", "题面"]), "题目说明");
  appendField(update, "requirements", extractAppendValue(text, ["完成要求", "提交要求", "验收要求", "要求"]), "完成要求");

  if (update.patch.tags === current.tags) {
    delete update.patch.tags;
  }
  return update;
}

function inferFreeformPreviewUpdate(text: string, current: AuthoringPreviewState): PreviewFieldUpdate {
  const update = emptyPreviewFieldUpdate();
  if (/(正式|严谨|规范|专业)/.test(text) && /(题目|题面|描述|说明|标题|改得|改成|一点|一些)/.test(text)) {
    const title = formalizeTitle(current.title);
    if (title !== current.title) {
      update.patch.title = title;
    }
    update.append.requirements =
      "提交内容需要使用规范表述，包含验证步骤、关键证据、影响判断和修复建议。";
    update.labels.push("题面表述已调整为更正式");
  }

  if (/(更详细|详细一点|再展开|说明多一点|讲清楚)/.test(text)) {
    update.append.description =
      "题面需要明确目标服务入口、建议验证顺序、期望观察点和提交材料边界，方便学生按步骤完成验证。";
    update.labels.push("题目说明已补充更详细的引导");
  }

  if (/(简单一点|更简单|降低门槛|适合新手|适合入门)/.test(text) && !/(难度|题目难度)/.test(text)) {
    update.append.summary = "题目会保留必要提示，适合学生从基础验证步骤开始完成。";
    update.labels.push("题目摘要已调整为更易上手");
  }

  if (/(GUI页面|GUI 页面|图形页面|可视化页面|浏览器页面|网页页面|前端页面)/i.test(text)) {
    update.append.description =
      "目标服务需要至少提供一个可通过浏览器访问的 GUI 页面，同时保留终端命令验证路径。";
    update.append.requirements =
      "学生需要访问 GUI 页面并结合终端请求说明页面行为、接口响应和安全影响之间的关系。";
    update.addTags.push("GUI页面");
    update.labels.push("已加入 GUI 页面要求");
  }

  if (/(组合.*(?:其他|别的)|(?:其他|别的).*组合|再组合|混合|融合|拼接|结合.*题目|多知识点)/.test(text)) {
    update.append.description =
      "题目设计优先组合兼容题库候选，形成一个主线清晰、知识点递进的综合实践。";
    update.addTags.push("组合题");
    update.labels.push("已优先按组合题方向调整");
  }

  if (/(安全提示|注意事项|敏感信息|不要泄露|token|Cookie|Authorization)/i.test(text)) {
    update.append.requirements =
      "提交材料不得包含真实密码、Cookie、Authorization、token、个人账号或其他敏感信息。";
    update.labels.push("完成要求已补充敏感信息保护要求");
  }
  return update;
}

function inferIntentUpdate(
  text: string,
  currentIntent: AuthoringCourseIntentState | null
): { constraints: Record<string, unknown>; labels: string[] } {
  const constraints: Record<string, unknown> = {};
  const labels: string[] = [];
  const currentDifficulty = clampDifficulty(currentIntent?.difficulty ?? 3);
  const exactDifficulty = explicitDifficulty(text);
  const relativeDifficulty = relativeDifficultyDelta(text);
  if (exactDifficulty !== null) {
    constraints.difficulty = exactDifficulty;
    constraints.maxDifficulty = Math.max(exactDifficulty, 5);
    labels.push(`难度已更新为 ${difficultyLabel(exactDifficulty)}`);
  } else if (relativeDifficulty !== 0) {
    const nextDifficulty = clampDifficulty(currentDifficulty + relativeDifficulty);
    constraints.difficulty = nextDifficulty;
    constraints.maxDifficulty = Math.max(nextDifficulty, 5);
    labels.push(`难度已调整为 ${difficultyLabel(nextDifficulty)}`);
  }

  const minutes = explicitExpectedMinutes(text);
  if (minutes !== null) {
    constraints.expectedMinutes = minutes;
    labels.push(`预计解题时间已更新为 ${minutes} 分钟`);
  }

  if (/(终端|命令行|CLI|curl|shell)/i.test(text) && /(只要|保持|使用|以|终端|命令行|CLI)/i.test(text)) {
    constraints.workspaceType = "TERMINAL";
    labels.push("工作区已保持为终端实践");
  }

  if (/(远程桌面|桌面环境|GUI工具|图形化工具)/i.test(text)) {
    constraints.workspaceType = "REMOTE_DESKTOP";
    labels.push("工作区已切换为远程桌面候选");
  }

  if (/(组合.*(?:其他|别的)|(?:其他|别的).*组合|再组合|混合|融合|拼接|结合.*题目|多知识点)/.test(text)) {
    constraints.preferComposition = true;
  }

  if (/(生成新环境|从零写|现场编写|定制靶场|不要题库|不用题库)/.test(text)) {
    constraints.preferCustomGeneration = true;
    labels.push("已优先按定制靶场方向处理");
  }

  if (/(至少.*GUI|GUI页面|GUI 页面|图形页面|浏览器页面|网页页面|前端页面)/i.test(text)) {
    constraints.requireGuiPage = true;
    constraints.category = "WEB";
  }

  return { constraints, labels };
}

function formalizeTitle(value: string): string {
  const clean = value.trim();
  if (!clean) return "课程安全实践专项";
  if (/(实践|专项|实验|训练)$/.test(clean)) return clean;
  return `${clean}实践`;
}

function setPatch(
  update: PreviewFieldUpdate,
  field: keyof AuthoringPreviewState,
  value: string | null,
  label: string
) {
  if (!value) return;
  update.patch[field] = value;
  update.labels.push(`${label}已更新为“${truncateLabel(value)}”`);
}

function appendField(
  update: PreviewFieldUpdate,
  field: keyof PreviewFieldUpdate["append"],
  value: string | null,
  label: string
) {
  if (!value) return;
  update.append[field] = value;
  update.labels.push(`${label}已补充“${truncateLabel(value)}”`);
}

function extractValue(text: string, aliases: string[], machineValue: boolean): string | null {
  const actions = "(?:改成|改为|设置为|设为|更新为|命名为|叫做|叫)";
  for (const alias of aliases) {
    const pattern = new RegExp(`${escapeRegExp(alias)}\\s*${actions}\\s*[：:，,]?\\s*(.+?)(?:[。；;]|$)`, "i");
    const match = text.match(pattern);
    if (match) {
      return cleanValue(match[1], machineValue);
    }
  }
  return null;
}

function extractAppendValue(text: string, aliases: string[]): string | null {
  const actions = "(?:增加|添加|补充|追加|加入|加上)";
  for (const alias of aliases) {
    const pattern = new RegExp(`${escapeRegExp(alias)}\\s*${actions}\\s*[：:，,]?\\s*(.+?)(?:[。；;]|$)`, "i");
    const match = text.match(pattern);
    if (match) {
      return cleanValue(match[1], false);
    }
  }
  return null;
}

function extractTagList(text: string, verbs: string[]): string[] {
  for (const verb of verbs) {
    const patterns = [
      new RegExp(`标签\\s*${verb}\\s*[：:，,]?\\s*(.+?)(?:[。；;]|$)`, "i"),
      new RegExp(`${verb}\\s*标签\\s*[：:，,]?\\s*(.+?)(?:[。；;]|$)`, "i"),
      new RegExp(`${verb}\\s*(?:标签)?\\s*[：:，,]?\\s*(.+?)\\s*标签(?:[。；;]|$)`, "i")
    ];
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return normalizeTags(match[1]);
    }
  }
  return [];
}

function inferPublishWindowUpdate(text: string, current: PublishWindow, now: Date): PublishWindowUpdate | null {
  if (!hasPublishSignal(text)) return null;

  const openAt = localInputToDate(current.openAt, now);
  const dueAt = localInputToDate(current.dueAt, new Date(openAt.getTime() + 2 * 60 * 60 * 1000));
  const previousDurationMs = Math.max(60 * 1000, dueAt.getTime() - openAt.getTime());

  let nextOpenAt = openAt;
  let nextDueAt = dueAt;
  let nextMode = current.mode;
  const labels: string[] = [];

  const startDate = parseStartDate(text, openAt);
  if (startDate) {
    nextOpenAt = startDate;
    nextDueAt = (current.mode ?? "duration") === "duration" ? new Date(startDate.getTime() + previousDurationMs) : dueAt;
    labels.push(`开始时间已更新为 ${formatLocalDateTime(toLocalInput(nextOpenAt))}`);
  }

  const deadline = parseDeadlineDate(text, openAt);
  if (deadline) {
    nextDueAt = deadline;
    nextMode = "explicit";
    labels.push(`结束时间已更新为 ${formatLocalDateTime(toLocalInput(nextDueAt))}`);
  } else {
    const duration = parseDuration(text);
    if (duration && hasDurationSignal(text)) {
      nextDueAt = addDuration(nextOpenAt, duration.amount, duration.unit);
      nextMode = "duration";
      labels.push(`结束时间已按持续时长更新为 ${formatLocalDateTime(toLocalInput(nextDueAt))}`);
    }
  }

  if (!labels.length) return null;
  if (nextDueAt.getTime() <= nextOpenAt.getTime()) {
    nextDueAt = new Date(nextOpenAt.getTime() + 2 * 60 * 60 * 1000);
    labels.push("结束时间早于开始时间，已自动顺延 2 小时");
  }

  const window = {
    openAt: toLocalInput(nextOpenAt),
    dueAt: toLocalInput(nextDueAt),
    mode: nextMode
  };
  return {
    window,
    label: `${formatLocalDateTime(window.openAt)} 至 ${formatLocalDateTime(window.dueAt)}`,
    labels
  };
}

function hasPublishSignal(text: string): boolean {
  if (/(解题时间|预计.*(?:分钟|小时)|学生预计)/.test(text) && !/(截止|持续|开放|发布|开始|结束|到期|关闭|下线)/.test(text)) {
    return false;
  }
  return /(发布|开放|开始|截止|结束|持续|到期|关闭|下线|上架|时间)/.test(text);
}

function hasDurationSignal(text: string): boolean {
  if (/(开始时间|开始|截止|结束).*\d{1,2}\s*月\s*\d{0,2}/.test(text) && !/(持续|开放.*(?:年|个月|周|天|小时)|发布持续|时间给)/.test(text)) {
    return false;
  }
  return /(持续|开放.*(?:年|月|周|天|小时)|发布.*(?:年|月|周|天|小时)|时间.*(?:年|月|周|天|小时))/.test(text);
}

function parseStartDate(text: string, base: Date): Date | null {
  const segment = temporalSegment(text, ["开始", "开放", "发布", "上架", "生效"], ["截止", "结束", "到期", "关闭", "下线"]);
  if (!segment) return null;
  return parseDateTime(segment, base, "start");
}

function parseDeadlineDate(text: string, base: Date): Date | null {
  const segment = temporalSegment(text, ["截止", "结束", "到期", "关闭", "下线"], []);
  if (!segment) return null;
  return parseDateTime(segment, base, "deadline");
}

function temporalSegment(text: string, startMarkers: string[], stopMarkers: string[]): string | null {
  const starts = startMarkers
    .map((marker) => text.indexOf(marker))
    .filter((index) => index >= 0)
    .sort((left, right) => left - right);
  if (!starts.length) return null;
  const start = starts[0];
  const stops = stopMarkers
    .map((marker) => text.indexOf(marker, start + 1))
    .filter((index) => index > start)
    .sort((left, right) => left - right);
  const end = stops[0] ?? text.length;
  const direct = text.slice(start, end);
  const punctuationIndex = direct.search(/[，,。；;]/);
  const directHead = punctuationIndex >= 0 ? direct.slice(0, punctuationIndex) : direct;
  if (hasDateExpression(directHead)) return directHead;
  return text.slice(Math.max(0, start - 14), end);
}

function hasDateExpression(text: string): boolean {
  return Boolean(
    /(20\d{2}|\d{1,2}\s*月\s*\d{1,2}|下下周|下周|本周|这周|周[一二三四五六日天]|星期[一二三四五六日天]|下下个月|下个月|下月|明天|明日|后天|今天|今日|今晚|月底|月末|\d{1,2}[:：]\d{1,2}|\d{1,2}\s*点)/.test(text)
  );
}

function parseDateTime(text: string, base: Date, mode: "start" | "deadline"): Date | null {
  const explicit = parseExplicitDate(text, base);
  if (explicit) return applyTime(text, explicit, base, mode);

  if (mode === "start") {
    const relative = parseRelativeDay(text, base, mode);
    if (relative) return applyTime(text, relative, base, mode);
    const weekday = parseWeekday(text, base);
    if (weekday) return applyTime(text, weekday, base, mode);
    return null;
  }

  const relative = parseRelativeDay(text, base, mode);
  if (relative) return applyTime(text, relative, base, mode);

  const weekday = parseWeekday(text, base);
  if (weekday) return applyTime(text, weekday, base, mode);

  return null;
}

function parseExplicitDate(text: string, base: Date): Date | null {
  const full = text.match(/(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?/);
  if (full) {
    return new Date(Number(full[1]), Number(full[2]) - 1, Number(full[3]), base.getHours(), base.getMinutes());
  }
  const monthDay = text.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?/);
  if (monthDay) {
    let year = base.getFullYear();
    const candidate = new Date(year, Number(monthDay[1]) - 1, Number(monthDay[2]), base.getHours(), base.getMinutes());
    if (candidate.getTime() < base.getTime() - 24 * 60 * 60 * 1000) {
      year += 1;
    }
    return new Date(year, Number(monthDay[1]) - 1, Number(monthDay[2]), base.getHours(), base.getMinutes());
  }
  return null;
}

function parseWeekday(text: string, base: Date): Date | null {
  const match = text.match(/(下下周|下周|本周|这周|周|星期)([一二三四五六日天])/);
  if (!match) {
    if (/下下周/.test(text)) return addDuration(base, 2, "week");
    if (/下周/.test(text)) return addDuration(base, 1, "week");
    return null;
  }
  const weekday = weekdayValue(match[2]);
  const current = base.getDay();
  let diff = (weekday - current + 7) % 7;
  if (match[1] === "下下周") diff += diff === 0 ? 14 : 7;
  else if (match[1] === "下周") diff += diff === 0 ? 7 : 0;
  else if (diff === 0) diff = 7;
  const result = new Date(base.getTime());
  result.setDate(result.getDate() + diff);
  return result;
}

function parseRelativeDay(text: string, base: Date, mode: "start" | "deadline"): Date | null {
  if (/下下个月|下下月/.test(text)) return addDuration(base, 2, "month");
  if (/下个月|下月/.test(text)) return addDuration(base, 1, "month");
  if (/月底|月末/.test(text)) {
    return new Date(base.getFullYear(), base.getMonth() + 1, 0, base.getHours(), base.getMinutes());
  }
  const duration = parseDuration(text);
  if (mode === "deadline" && duration && /(后|内|持续)/.test(text)) return addDuration(base, duration.amount, duration.unit);
  if (mode === "deadline" && /(下下周|下周|本周|这周|周[一二三四五六日天]|星期[一二三四五六日天])/.test(text)) {
    return null;
  }
  if (/这个月|本月/.test(text)) return new Date(base.getTime());
  if (/后天/.test(text)) return addDuration(base, 2, "day");
  if (/明天|明日/.test(text)) return addDuration(base, 1, "day");
  if (/今天|今日|今晚/.test(text)) return new Date(base.getTime());
  return null;
}

function explicitDifficulty(text: string): number | null {
  if (/(非常难|极难|专家|高难)/.test(text)) return 5;
  if (/(较高|较难|偏难|偏高|困难|高级|难度大)/.test(text)) return 4;
  if (/(中等|中级|适中)/.test(text)) return 3;
  if (/(基础|普通|一般)/.test(text)) return 2;
  if (/(入门|简单|容易|新手|低难度)/.test(text)) return 1;
  const numeric = text.match(/难度\s*(?:改成|改为|设置为|设为)?\s*([1-5])\s*(?:级|星|分)?/);
  if (numeric) return clampDifficulty(Number(numeric[1]));
  return null;
}

function relativeDifficultyDelta(text: string): number {
  if (/(难度|题目).*(加大|提高|提升|更难|难一点|难一些|上调|拔高)/.test(text)) return 1;
  if (/(加大|提高|提升|更难|难一点|难一些|上调|拔高).*(难度|题目)/.test(text)) return 1;
  if (/(难度|题目).*(降低|下降|简单点|简单一点|简单一些|容易点|容易一点|下调)/.test(text)) return -1;
  if (/(降低|下降|简单点|简单一点|简单一些|容易点|容易一点|下调).*(难度|题目)/.test(text)) return -1;
  return 0;
}

function explicitExpectedMinutes(text: string): number | null {
  if (!/(预计|解题|完成|时长|耗时|控制|时间)/.test(text)) return null;
  const minute = text.match(/(\d{1,3})\s*(?:min|minute|minutes|分钟)/i);
  if (minute) return Math.max(1, Number(minute[1]));
  const hour = text.match(/(\d{1,2})\s*(?:hour|hours|小时)/i);
  if (hour) return Math.max(1, Number(hour[1]) * 60);
  return null;
}

function clampDifficulty(value: number): number {
  return Math.max(1, Math.min(5, Math.round(value)));
}

function difficultyLabel(value: number): string {
  if (value <= 1) return "入门";
  if (value === 2) return "基础";
  if (value === 3) return "中等";
  if (value === 4) return "较难";
  return "高难";
}

function applyTime(text: string, date: Date, base: Date, mode: "start" | "deadline"): Date {
  const result = new Date(date.getTime());
  const colon = text.match(/(\d{1,2})[:：](\d{1,2})/);
  const hourText = text.match(/(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分?)?/);
  if (colon) {
    result.setHours(Number(colon[1]), Number(colon[2]), 0, 0);
    return result;
  }
  if (hourText) {
    result.setHours(Number(hourText[1]), Number(hourText[2] ?? 0), 0, 0);
    return result;
  }
  if (mode === "deadline" && /(今天|今日|今晚|\d{1,2}\s*月\s*\d{1,2}|20\d{2}|周[一二三四五六日天]|星期[一二三四五六日天])/.test(text)) {
    result.setHours(23, 59, 0, 0);
    return result;
  }
  result.setHours(base.getHours(), base.getMinutes(), 0, 0);
  return result;
}

function parseDuration(text: string): { amount: number; unit: DurationUnit } | null {
  if (/半年/.test(text)) return { amount: 6, unit: "month" };
  const match = text.match(/([0-9]+|[一二两三四五六七八九十]+)\s*(年|个月|月|周|星期|天|日|小时)/);
  if (!match) return null;
  const amount = parseDurationAmount(match[1]);
  if (!amount) return null;
  const unitText = match[2];
  if (unitText === "年") return { amount, unit: "year" };
  if (unitText === "个月" || unitText === "月") return { amount, unit: "month" };
  if (unitText === "周" || unitText === "星期") return { amount, unit: "week" };
  if (unitText === "小时") return { amount, unit: "hour" };
  return { amount, unit: "day" };
}

function parseDurationAmount(value: string): number {
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) return numeric;
  const digits: Record<string, number> = {
    一: 1,
    二: 2,
    两: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9
  };
  if (value === "十") return 10;
  if (value.includes("十")) {
    const [left, right] = value.split("十");
    const tens = left ? digits[left] ?? 0 : 1;
    const ones = right ? digits[right] ?? 0 : 0;
    return tens * 10 + ones;
  }
  return digits[value] ?? 0;
}

function addDuration(date: Date, amount: number, unit: DurationUnit): Date {
  const next = new Date(date.getTime());
  if (unit === "year") next.setFullYear(next.getFullYear() + amount);
  if (unit === "month") next.setMonth(next.getMonth() + amount);
  if (unit === "week") next.setDate(next.getDate() + amount * 7);
  if (unit === "day") next.setDate(next.getDate() + amount);
  if (unit === "hour") next.setHours(next.getHours() + amount);
  return next;
}

function weekdayValue(value: string): number {
  if (value === "日" || value === "天") return 0;
  return { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6 }[value] ?? 1;
}

function normalizeTags(value: string): string[] {
  return value
    .replace(/[“”"'`]/g, "")
    .split(/[,，、\s]+/)
    .map((tag) => tag.trim())
    .filter(Boolean)
    .slice(0, 20);
}

function cleanValue(value: string, machineValue: boolean): string | null {
  let next = value.trim().replace(/^[“”"'`]+|[“”"'`]+$/g, "");
  next = next.replace(/[。；;]+$/g, "").trim();
  if (machineValue) {
    next = next.match(/[A-Za-z0-9_.:-]+/)?.[0] ?? "";
  }
  return next || null;
}

function truncateLabel(value: string): string {
  return value.length > 32 ? `${value.slice(0, 32)}...` : value;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
