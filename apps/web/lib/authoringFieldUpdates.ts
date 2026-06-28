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
};

export type PublishWindowUpdate = {
  window: PublishWindow;
  label: string;
  labels: string[];
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
  labels: string[];
  hasChanges: boolean;
};

type DurationUnit = "year" | "month" | "week" | "day" | "hour";

const TEXT_FIELDS = ["summary", "description", "requirements"] as const;

export function inferAuthoringFieldUpdate(
  text: string,
  currentPreview: AuthoringPreviewState,
  currentPublishWindow: PublishWindow,
  now = new Date()
): AuthoringFieldUpdate {
  const preview = inferPreviewFieldUpdate(text, currentPreview);
  const publish = inferPublishWindowUpdate(text, currentPublishWindow, now);
  const labels = [...preview.labels, ...(publish?.labels ?? [])];
  return {
    preview,
    publish,
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
  appendField(update, "requirements", extractAppendValue(text, ["完成要求", "提交要求", "验收要求"]), "完成要求");

  if (update.patch.tags === current.tags) {
    delete update.patch.tags;
  }
  return update;
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
  const labels: string[] = [];

  const startDate = parseStartDate(text, openAt);
  if (startDate) {
    nextOpenAt = startDate;
    nextDueAt = new Date(startDate.getTime() + previousDurationMs);
    labels.push(`开始时间已更新为 ${formatLocalDateTime(toLocalInput(nextOpenAt))}`);
  }

  const deadline = parseDeadlineDate(text, nextOpenAt);
  if (deadline) {
    nextDueAt = deadline;
    labels.push(`结束时间已更新为 ${formatLocalDateTime(toLocalInput(nextDueAt))}`);
  } else {
    const duration = parseDuration(text);
    if (duration && hasDurationSignal(text)) {
      nextDueAt = addDuration(nextOpenAt, duration.amount, duration.unit);
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
    dueAt: toLocalInput(nextDueAt)
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
  return text.slice(start, end);
}

function parseDateTime(text: string, base: Date, mode: "start" | "deadline"): Date | null {
  const explicit = parseExplicitDate(text, base);
  if (explicit) return applyTime(text, explicit, base, mode);

  const weekday = parseWeekday(text, base);
  if (weekday) return applyTime(text, weekday, base, mode);

  const relative = parseRelativeDay(text, base);
  if (relative) return applyTime(text, relative, base, mode);

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

function parseRelativeDay(text: string, base: Date): Date | null {
  if (/后天/.test(text)) return addDuration(base, 2, "day");
  if (/明天|明日/.test(text)) return addDuration(base, 1, "day");
  if (/今天|今日|今晚/.test(text)) return new Date(base.getTime());
  const duration = parseDuration(text);
  if (duration && /(后|内|持续)/.test(text)) return addDuration(base, duration.amount, duration.unit);
  return null;
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
