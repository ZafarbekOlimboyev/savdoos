// Vitest BAJARILGANINI isbotlash (CI `unit` job'i) — pytest uchun `verify_pytest_run.py` ning jufti.
//
// ⚠️  NEGA "numPassedTests === numTotalTests" YETARLI EMAS: `vitest.config.ts` dagi `include` torayib
//     qolsa yoki sinov fayli boshqa joyga ko'chsa, vitest KAMROQ sinov topadi, hammasi o'tadi va darvoza
//     "OK" deydi — Phase 5F kafolatlari (sinov chop etish yozmaydi, ESC/POS oq ro'yxati, XSS escape,
//     bitta avto-chop) CI'da jimgina tekshirilmay qolardi. Shu bois:
//       1. diskdagi HAR `tests/**/*.test|spec.ts(x)` fayli JSON natijada bo'lishi va o'tishi SHART;
//       2. har faylda kamida bitta O'TGAN sinov bo'lsin (bo'sh fayl ham "o'tadi");
//       3. skip/todo YO'Q (vitest ularni numTotalTests ga qo'shadi, lekin o'tgan deb sanamaydi);
//       4. umumiy son pastki chegaradan kam emas.
// Foydalanish: node scripts/ci/verify_vitest_run.cjs vitest.json [min_total]
const fs = require("fs");
const path = require("path");

const [, , jsonPath = "vitest.json", minArg = "20"] = process.argv;
const r = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
const MIN_TOTAL = Number(minArg);
const root = process.cwd();
const errors = [];

function walk(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name.startsWith(".")) continue;
      walk(p, out);
    } else if (/\.(test|spec)\.tsx?$/.test(e.name)) {
      out.push(path.relative(root, p).split(path.sep).join("/"));
    }
  }
  return out;
}

const onDisk = walk(path.join(root, "tests"), []);
const byFile = new Map();
for (const f of r.testResults || []) {
  byFile.set(path.relative(root, f.name).split(path.sep).join("/"), f);
}

for (const rel of onDisk) {
  const f = byFile.get(rel);
  if (!f) { errors.push(`bajarilmagan fayl (include'dan tashqarida?): ${rel}`); continue; }
  if (f.status !== "passed") errors.push(`fayl o'tmadi: ${rel} (${f.status})`);
  const res = f.assertionResults || [];
  if (!res.some((a) => a.status === "passed")) errors.push(`faylda o'tgan sinov yo'q: ${rel}`);
  for (const a of res) {
    if (a.status !== "passed") errors.push(`${a.status}: ${rel} › ${a.fullName}`);
  }
}
if (r.numFailedTests !== 0) errors.push(`yiqilgan sinovlar: ${r.numFailedTests}`);
if (r.numPassedTests !== r.numTotalTests) {
  errors.push(`o'tmagan (skip/todo) sinovlar: ${r.numTotalTests - r.numPassedTests}`);
}
if (!(r.numTotalTests >= MIN_TOTAL)) errors.push(`sinovlar soni ${r.numTotalTests} < ${MIN_TOTAL}`);

if (errors.length) {
  console.error("VITEST BAJARILISH ISBOTI YIQILDI:\n  " + errors.join("\n  "));
  process.exit(1);
}
console.log(`OK ${r.numPassedTests} sinov, ${onDisk.length} fayl (har biri bajarildi va o'tdi)`);
