// Ko'rib chiqish uchun kadrlar: BIR marta bundle, ko'p kadr.
//   node scripts/stills.mjs ProofOfStyle 30 96 140
// (`remotion still` har chaqiruvda qayta bundle qiladi — sekin.)
import { bundle } from '@remotion/bundler';
import { renderStill, selectComposition } from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const [id = 'ProofOfStyle', ...frames] = process.argv.slice(2);
const out = path.join(ROOT, 'out', 'stills');
fs.mkdirSync(out, { recursive: true });
const serveUrl = await bundle({ entryPoint: path.join(ROOT, 'src/index.ts') });
const composition = await selectComposition({ serveUrl, id, inputProps: {} });
for (const fr of frames.map(Number)) {
  const file = path.join(out, `f${fr}.png`);
  await renderStill({ serveUrl, composition, frame: fr, output: file, imageFormat: 'png', overwrite: true });
  console.log(file);
}
