import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vm from "node:vm";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { LOGO_64x16, saleDto, FULL_TEMPLATE } from "./__golden__/receipt/fixtures";
import * as R from "@/receipt";

// Phase 5F F1: `packages/shared/src/receipt/**` Electron MAIN jarayoniga ham yig'iladi (vite-plugin-electron,
// `@` alias'siz). Shu bois: faqat nisbiy importlar; React/DOM/localStorage/zustand yo'q; va paket alias'siz
// esbuild bilan yig'ilib, DOM'siz toza `vm` kontekstida AYNAN bir xil natija beradi.

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const LIB = path.join(ROOT, "packages", "shared", "src", "receipt");

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => (l.trimStart().startsWith("//") ? "" : l.replace(/\s\/\/\s.*$/, "")))
    .join("\n");
}

describe("receipt/ — sof modul (Electron main uchun yaroqli)", () => {
  const files = fs.readdirSync(LIB).filter((f) => f.endsWith(".ts"));

  it("papkada kutilgan modullar bor", () => {
    for (const f of ["types.ts", "profiles.ts", "format.ts", "labels.ts", "layout.ts", "html.ts", "escpos.ts",
      "sample.ts", "provisional.ts", "index.ts"]) {
      expect(files).toContain(f);
    }
  });

  it("importlar faqat nisbiy './x'; taqiqlangan global va kutubxonalar yo'q", () => {
    const FORBIDDEN = [
      /@\//, /\breact\b/i, /\bzustand\b/, /\bwindow\b/, /\bdocument\b/, /\blocalStorage\b/, /\bsessionStorage\b/,
      /\bnavigator\b/, /\brequire\(/, /\bprocess\./, /\bBuffer\b/, /\batob\b/, /\bbtoa\b/, /\bTextEncoder\b/,
      /\bIntl\b/, /\bDate\b/, /\bMath\.random\b/, /\btoLocale\w*\(/, /\bfetch\(/,
    ];
    for (const f of files) {
      const src = fs.readFileSync(path.join(LIB, f), "utf8");
      const specs = [...src.matchAll(/(?:import|export)\s[^;]*?from\s+["']([^"']+)["']/g)].map((m) => m[1]);
      for (const s of specs) expect(s, `${f}: ${s}`).toMatch(/^\.\/[a-z0-9]+$/);
      expect(src, f).not.toMatch(/\bimport\s*\(/); // dinamik import yo'q
      const code = stripComments(src);
      for (const re of FORBIDDEN) expect(code, `${f}: ${re}`).not.toMatch(re);
    }
  });

  it("esbuild bilan alias'siz yig'iladi va DOM'siz vm kontekstida bir xil natija beradi", () => {
    // esbuild JS API alohida node jarayonida: jsdom muhitida esbuild'ning TextEncoder tekshiruvi yiqiladi,
    // `bin/esbuild` esa Linux'da native binar (node bilan ishga tushmaydi).
    const script =
      'const r=require("esbuild").buildSync({entryPoints:[process.argv[1]],bundle:true,platform:"neutral",' +
      'format:"cjs",write:false,logLevel:"error"});process.stdout.write(r.outputFiles[0].text);';
    const code = execFileSync(process.execPath, ["-e", script, path.join(LIB, "index.ts")], {
      cwd: ROOT, encoding: "utf8", maxBuffer: 16 * 1024 * 1024,
    });
    expect(code).not.toMatch(/\brequire\(/); // tashqi bog'liqlik yo'q (node builtin ham)
    const sandbox: Record<string, unknown> = { module: { exports: {} } };
    sandbox.exports = (sandbox.module as { exports: object }).exports;
    const ctx = vm.createContext(sandbox);
    vm.runInContext(code, ctx, { filename: "receipt.bundle.js" });
    expect(vm.runInContext("typeof window + typeof document + typeof localStorage", ctx)).toBe("undefinedundefinedundefined");
    const M = (sandbox.module as { exports: typeof R }).exports;

    const dto = JSON.parse(JSON.stringify(saleDto()));
    const opts = { width_mm: 80 as const, lang: "ru" as const, template: FULL_TEMPLATE, logo: LOGO_64x16 };
    const docVm = M.layoutReceipt(dto, opts);
    const docHere = R.layoutReceipt(saleDto(), opts);
    expect(JSON.stringify(docVm)).toBe(JSON.stringify(docHere));
    expect(M.renderHtml(docVm)).toBe(R.renderHtml(docHere));
    const p = R.profileFor("epson80", 80);
    expect(Array.from(M.encodeEscPos(docVm, p).bytes)).toEqual(Array.from(R.encodeEscPos(docHere, p).bytes));
    const g = R.profileFor("generic58", 58);
    const d58 = R.layoutReceipt(saleDto(), { ...opts, width_mm: 58 });
    expect(Array.from(M.encodeEscPos(M.layoutReceipt(dto, { ...opts, width_mm: 58 }), g).bytes))
      .toEqual(Array.from(R.encodeEscPos(d58, g).bytes));
  });
});
