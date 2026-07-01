import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(import.meta.url);
const ts = require("typescript");

function loadTsModule(relativePath) {
  const sourcePath = join(root, relativePath);
  const compiled = ts.transpileModule(readFileSync(sourcePath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true
    }
  });
  const module = { exports: {} };
  const localRequire = createRequire(sourcePath);
  Function("require", "module", "exports", compiled.outputText)(localRequire, module, module.exports);
  return module.exports;
}

const { teacherChallengeBankHref } = loadTsModule("lib/navigation.ts");

assert.equal(teacherChallengeBankHref(), "/teacher/challenge-bank");
assert.equal(
  teacherChallengeBankHref("bank A/B?中文"),
  "/teacher/challenge-bank?created=bank%20A%2FB%3F%E4%B8%AD%E6%96%87"
);

const createPageSource = readFileSync(join(root, "components/TeacherChallengeCreatePage.tsx"), "utf8");
assert.match(createPageSource, /teacherChallengeBankHref\(createdItem\.itemId\)/);
assert.doesNotMatch(createPageSource, /<Link\s+href=\{`\/teacher\/challenge-bank\?created=/);

console.log("教师创建页导航契约测试通过。");
