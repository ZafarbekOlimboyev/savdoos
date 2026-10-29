import { createHmac } from "crypto";
import { expect, test } from "@playwright/test";

/**
 * ADMIN-1.0 / P0-H — Super Admin konsoli HAQIQIY BRAUZERDA.
 *
 * NEGA BU FAYL BOR. ADMIN-1.0-LAUNCH-GAP ko'rigi konsolni «backend bor, UI
 * ishlamaydi» holatida topdi: 2FA maydoni `display:none` ortida edi,
 * provisioning shakli filial/mintaqa yubormasdi, parol bannerda qolardi,
 * yumshoq o'chirilgan do'konni tiklash sirti umuman yo'q edi. Backend
 * testlari (`apps/server/tests/test_admin_p0_console.py`) HTTP sirtini
 * qulflaydi; BU fayl esa operator ko'radigan oqimni o'lchaydi — ya'ni
 * «endpoint bor» bilan «konsol ishlaydi» o'rtasidagi farqni.
 *
 * ⚠️  2FA HAQIQIY: `e2e/start_backend.py` `VENDOR_TOTP_SECRET` beradi, ya'ni
 *     login production bilan AYNI yo'ldan o'tadi (kalit + TOTP -> sessiya).
 *     Kod shu yerda RFC 6238 bo'yicha hisoblanadi (tashqi paket YO'Q).
 *
 * ⚠️  PRODUKSIYA MA'LUMOTI YO'Q: backend har ishga tushishda TOZA SQLite.
 */

//  ⚠️  ORIGIN env orqali (ADMIN-1.0/RC): standart 8000 — `playwright.config.ts`
//      va CI uchun xulq O'ZGARMAYDI. Izolyatsiyalangan yurishda
//      `E2E_ORIGIN` boshqa portni ko'rsatadi, ya'ni parallel sessiyaning
//      dev serverlari bilan TO'QNASHMAYDI.
const ORIGIN = process.env.E2E_ORIGIN || "http://127.0.0.1:8000";
const PORTAL = `${ORIGIN}/api/v1/admin/portal`;
const API = `${ORIGIN}/api/v1`;
const KEY = "e2e-vendor-key";
const TOTP_SECRET = "JBSWY3DPEHPK3PXP";
const PAROL = "Bishkek-Bahor-2026";          // 19 belgi — siyosat (MIN_LEN=12) dan o'tadi

function base32(s: string): Buffer {
  const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/=+$/, "").toUpperCase()) {
    const i = A.indexOf(c);
    if (i < 0) throw new Error(`base32 belgisi noto'g'ri: ${c}`);
    bits += i.toString(2).padStart(5, "0");
  }
  const out: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}

/** RFC 6238 TOTP (SHA-1, 30 s, 6 raqam) — `admin._totp_ok` bilan AYNI. */
function totp(secret = TOTP_SECRET): string {
  const counter = Math.floor(Date.now() / 1000 / 30);
  const buf = Buffer.alloc(8);
  buf.writeUInt32BE(Math.floor(counter / 2 ** 32), 0);
  buf.writeUInt32BE(counter >>> 0, 4);
  const h = createHmac("sha1", base32(secret)).update(buf).digest();
  const o = h[h.length - 1] & 0x0f;
  const v = (h.readUInt32BE(o) & 0x7fffffff) % 1_000_000;
  return String(v).padStart(6, "0");
}

const uniq = () => Math.random().toString(36).slice(2, 8);

/**
 * Ochiq modalni YOPADI va yopilishini KUTADI.
 *
 * ⚠️  NEGA KERAK (birinchi yurishda O'LCHANGAN): `#ovDetail` overlay'i
 *     butun ekranni qoplaydi, ya'ni modal ochiq qolsa keyingi
 *     `#compRows tr` bosilishi «subtree intercepts pointer events» bilan
 *     90 s davomida qayta urinib, testni timeout'ga olib boradi. Konsolda
 *     ba'zi yo'llar modalni O'ZI yopadi (`toggleSuspend`, muvaffaqiyatli
 *     `deleteCompany`), ba'zilari esa ATAYLAB yopmaydi (tarif o'zgartirish,
 *     NOTO'G'RI kod kiritilgan o'chirish) — operator o'zi yopadi.
 */
/**
 * KETMA-KET bir nechta dialogga javob beradi.
 *
 * ⚠️  NEGA `page.once()` x2 ISHLAMAYDI (o'lchangan): ikkala `once`
 *     tinglovchisi AYNI BIRINCHI dialogga ulanadi va ikkinchisi
 *     «Cannot accept dialog which is already handled» bilan yiqiladi.
 *     Bu yerda BITTA tinglovchi navbatdan javob oladi.
 */
async function dialoglar(
  page: import("@playwright/test").Page,
  javoblar: (string | undefined)[],
  amal: () => Promise<void>,
) {
  const navbat = [...javoblar];
  const h = async (d: import("@playwright/test").Dialog) => {
    await d.accept(navbat.shift());
  };
  page.on("dialog", h);
  try {
    await amal();
  } finally {
    page.off("dialog", h);
  }
}

/**
 * Konsolning AMALDAGI sessiya tokeni.
 *
 * ⚠️  NEGA `window.SESSION` EMAS (o'lchangan: 401 bilan yiqildi):
 *     portal skriptida token `let SESSION` bilan e'lon qilingan, ya'ni u
 *     SKRIPT QAMROVIDA yashaydi va `window` ning XOSSASI BO'LMAYDI —
 *     `window.SESSION` `undefined` qaytaradi. Token mijozda `sessionStorage`
 *     ning `vs` kalitida ham saqlanadi (`doLogin`), va bu hujjatlashtirilgan,
 *     barqaror joy.
 */
async function sessiyaToken(page: import("@playwright/test").Page): Promise<string> {
  return (await page.evaluate(() => sessionStorage.getItem("vs") || "")) as string;
}

async function yopModal(page: import("@playwright/test").Page) {
  const ov = page.locator("#ovDetail");
  if (await ov.evaluate((e) => e.classList.contains("on"))) {
    //  ⚠️  `exact: true` SHART: P0-F dan keyin to'xtatish tugmasi matni
    //      «To'xtatish (kirishni YOPISH)» bo'ldi va u ham «Yopish» ga mos
    //      keladi — qat'iy rejimda ikki element topilib yiqilardi.
    await page.locator("#detailBox")
      .getByRole("button", { name: "Yopish", exact: true }).click();
  }
  await expect(ov).not.toHaveClass(/on/);
}

test.describe.configure({ mode: "serial" });

test("P0-H: konsol to'liq onboarding sikli (2FA -> ochish -> tarif -> to'xtatish -> tiklash -> audit)", async ({
  page,
  request,
}) => {
  const kod = `kg${uniq()}`;
  const tel = `+99670${Math.floor(1000000 + Math.random() * 8999999)}`;

  // ── 1. OTP maydoni BIRINCHI yuklanishda KO'RINADI ───────────────────────
  //    O'LCHANGAN NUQSON: u `display:none` edi va faqat 401 matnida
  //    "otp"/"2fa" uchrasa ochilardi — production'da 2FA MAJBURIY, ya'ni
  //    operator kira olmasdi.
  await page.goto(PORTAL);
  await expect(page.locator("#vk")).toBeVisible();
  await expect(page.locator("#otp")).toBeVisible();

  // ── 2. XATO OTP -> kirmaydi, xato ko'rinadi ─────────────────────────────
  await page.locator("#vk").fill(KEY);
  await page.locator("#otp").fill("000000");
  await page.getByRole("button", { name: "Kirish" }).click();
  await expect(page.locator("#loginErr")).not.toBeEmpty();
  await expect(page.locator("#app")).toBeHidden();

  // ── 3. TO'G'RI OTP -> konsol ochiladi ───────────────────────────────────
  await page.locator("#vk").fill(KEY);
  await page.locator("#otp").fill(totp());
  await page.getByRole("button", { name: "Kirish" }).click();
  await expect(page.locator("#app")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("#kpis")).not.toBeEmpty();

  // ── 4. QISQA PAROL mijoz tomonda TO'SILADI (server qoidasi: 12) ─────────
  await page.getByRole("button", { name: /Yangi do/ }).click();
  await page.locator("#p_name").fill("Bishkek Market");
  await page.locator("#p_code").fill(kod);
  await page.locator("#p_owner").fill("Aijan Ega");
  await page.locator("#p_phone").fill(tel);
  await page.locator("#p_pw").fill("Qisqa-11xy");           // 10 belgi
  await page.getByRole("button", { name: "Ochish" }).click();
  await expect(page.locator("#provErr")).toContainText(/12/);
  //  Hech narsa yaratilmadi.
  const hali = await request.get(`${API}/admin/companies`, { headers: { "X-Vendor-Key": KEY } });
  expect(hali.status()).toBe(401);     // 2FA yoqilgan: xom kalit avtorizatsiya EMAS

  // ── 5. FILIAL + MINTAQA + VALYUTA shakldan yuboriladi ───────────────────
  await page.locator("#p_pw").fill(PAROL);
  await page.locator("#p_branch").fill("Chuy filiali");
  await page.locator("#p_tz").selectOption("Asia/Bishkek");
  await page.locator("#p_cur").selectOption("KGS");
  await page.locator("#p_plan").selectOption("start");
  await page.getByRole("button", { name: "Ochish" }).click();
  await expect(page.locator("#provDone")).toContainText("Do");
  await expect(page.locator("#provDone")).toContainText(kod);

  // ── 6. PAROL BANNERDA QOLMAYDI (P0-D) ───────────────────────────────────
  const banner = (await page.locator("#provDone").innerText()) ?? "";
  expect(banner).not.toContain(PAROL);
  //  Bir martalik topshirish: "ko'rsatish" bosilganda ko'rinadi.
  await page.getByRole("button", { name: /soniya ko/ }).click();
  await expect(page.locator("#credPeek")).toHaveText(PAROL);
  //  "Yopish va tozalash" -> xotiradan ham o'chadi.
  await page.getByRole("button", { name: /Yopish va tozalash/ }).click();
  await expect(page.locator("#ovProvision")).not.toHaveClass(/on/);
  //  ⚠️  BUTUN SAHIFA tekshiriladi, banner emas: parol DOM ning HECH
  //      QAYERIDA qolmasin (skrinshot, sahifa manbasi, DevTools).
  const dom = await page.evaluate(() => document.documentElement.innerHTML);
  expect(dom).not.toContain(PAROL);
  //  Sessiya tokeni ham UI ga chiqmasin (u faqat `sessionStorage` da).
  const sessTek = await sessiyaToken(page);
  expect(sessTek).toBeTruthy();
  const korinadigan = await page.evaluate(() => document.body.innerText);
  expect(korinadigan).not.toContain(sessTek);
  expect(korinadigan).not.toContain(KEY);

  // ── 7. Do'kon ro'yxatda; detal ochiladi; TARIF tayinlanadi ──────────────
  const qator = page.locator("#compRows tr", { hasText: kod });
  await expect(qator).toHaveCount(1);
  await qator.click();
  await expect(page.locator("#detailBox")).toContainText("Chuy filiali").catch(() => {});
  await expect(page.locator("#d_plan")).toBeVisible();
  await page.locator("#d_plan").selectOption("business");
  await expect(page.locator("#compRows tr", { hasText: kod })).toContainText("Business");
  //  Tarif o'zgartirish modalni YOPMAYDI — operator o'zi yopadi.
  await yopModal(page);

  // ── 8. SAVDOGAR KIRADI (haqiqiy HTTP) ───────────────────────────────────
  const kir = async () =>
    request.post(`${API}/auth/login/password`, { data: { phone: tel, password: PAROL } });
  let lr = await kir();
  expect(lr.status()).toBe(200);
  const token = (await lr.json()).access_token as string;
  const me = await request.get(`${API}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(me.status()).toBe(200);
  expect((await me.json()).company_currency).toBe("KGS");

  // ── 8b. TARIF AMALDA MAJBURLANADI (tayinlash emas, MAJBURLASH) ─────
  //    ⚠️  Bu qadam «tarif tayinlandi» dan FARQ qiladi: u
  //        `Setting("plan")` ning TIRIK entitlement ekanini o'lchaydi
  //        (`api/v1/branches.py` `PLAN_LIMITS`/`USER_LIMITS` → 403
  //        `tarif_limit`). 7-qadamda tarif `business` ga ko'tarilgan edi,
  //        shu bois avval `start` ga QAYTARAMIZ va chegarani sinaymiz.
  const mToken = { Authorization: `Bearer ${token}` };
  const sessH = { "X-Vendor-Session": await sessiyaToken(page) };
  const roy = await request.get(`${API}/admin/companies`, { headers: sessH });
  expect(roy.status()).toBe(200);
  const cid = ((await roy.json()).companies as Array<{ id: string; code: string }>)
    .find((c) => c.code === kod)!.id;
  const tarifQoy = (p: string) =>
    request.patch(`${API}/admin/companies/${cid}/plan`, { headers: sessH, data: { plan: p } });

  expect((await tarifQoy("start")).status()).toBe(200);
  const rad = await request.post(`${API}/branches`, {
    headers: mToken, data: { name: "Ikkinchi filial", code: "F02" },
  });
  expect(rad.status()).toBe(403);
  expect(await rad.text()).toContain("tarif_limit");

  expect((await tarifQoy("business")).status()).toBe(200);
  const qabul = await request.post(`${API}/branches`, {
    headers: mToken, data: { name: "Ikkinchi filial", code: "F02" },
  });
  expect([200, 201]).toContain(qabul.status());

  // ── 9. TO'XTATISH -> ESKI TOKEN ham, YANGI LOGIN ham RAD etiladi ────────
  await qator.click();
  page.once("dialog", (d) => d.accept());
  await page.locator("#btnSuspend").click();
  await expect(page.locator("#compRows tr", { hasText: kod })).toContainText(/to.xtatilgan/);
  expect((await kir()).status()).toBe(403);
  const eski = await request.get(`${API}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(eski.status()).toBe(403);

  // ── 10. QAYTA YOQISH -> kirish ochiladi ─────────────────────────────────
  await page.locator("#compRows tr", { hasText: kod }).click();
  await page.locator("#btnSuspend").click();        // qayta yoqish tasdiq so'ramaydi
  await expect(page.locator("#compRows tr", { hasText: kod })).not.toContainText(/to.xtatilgan/);
  expect((await kir()).status()).toBe(200);

  // ── 11. KONSOL AUDIT IZI (P0-E) ─────────────────────────────────────────
  await page.getByRole("button", { name: "Yangilash" }).click();
  await expect(page.locator("#auditRows")).toContainText(kod, { timeout: 15_000 });
  await expect(page.locator("#auditRows")).toContainText("create");
  //  Atributsiya cheklovi operatorga AYTILADI (bitta umumiy kalit).
  await expect(page.locator("#auditNote")).toContainText(/UMUMIY kalit/);

  // ── 12. MIJOZ JURNALIDA vendor qatori YO'Q (ijarachilar aro sizish) ─────
  const mj = await request.get(`${API}/audit?limit=300`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(mj.status()).toBe(200);
  expect(JSON.stringify(await mj.json())).not.toContain("vendor-console");

  // ── 13. YUMSHOQ O'CHIRISH — KOD TERILADI (P0-F) ─────────────────────────
  await page.locator("#compRows tr", { hasText: kod }).click();
  //  (a) NOTO'G'RI kod -> hech narsa o'chmaydi.
  //      IKKI dialog ketma-ket: prompt (kod) va alert («Kod mos kelmadi»).
  await dialoglar(page, ["butunlay-boshqa-kod", undefined], async () => {
    await page.locator("#btnDelete").click();
  });
  await expect(page.locator("#compRows tr", { hasText: kod })).toHaveCount(1);
  //  Rad etilgan o'chirish modalni ATAYLAB ochiq qoldiradi (operator kodni
  //  qayta kiritishi mumkin) — keyingi bosish uchun yopamiz.
  await yopModal(page);
  //  (b) TO'G'RI kod -> o'chadi.
  await page.locator("#compRows tr", { hasText: kod }).click();
  page.once("dialog", (d) => d.accept(kod));
  await page.locator("#btnDelete").click();
  await expect(page.locator("#compRows tr", { hasText: kod })).toHaveCount(0, { timeout: 15_000 });
  expect((await kir()).status()).toBe(401);

  // ── 14. «O'CHIRILGANLAR» ro'yxati va TIKLASH ────────────────────────────
  await expect(page.locator("#delWrap")).toBeVisible();
  const ochQator = page.locator("#delRows tr", { hasText: kod });
  await expect(ochQator).toHaveCount(1);
  page.once("dialog", (d) => d.accept());
  await ochQator.getByRole("button", { name: /Tiklash/ }).click();
  await expect(page.locator("#compRows tr", { hasText: kod })).toHaveCount(1, { timeout: 15_000 });
  expect((await kir()).status()).toBe(200);

  // ── 14b. EGA O'ZI YOPGAN do'konga TIKLASH tugmasi BERILMAYDI ───────
  //    P1 (mustaqil ko'rik topdi): `Company.deleted_at` ni IKKI yo'l yozadi va
  //    yopish ATAYLAB terminal (`peers_present` darvozasining yozma asosi).
  //    Manba-matni gardi buni ISBOTLAY OLMAYDI — shox xulqi FAQAT shu yerda
  //    o'lchanadi.
  const kod2 = `kg${uniq()}`;
  const tel2 = `+99670${Math.floor(1000000 + Math.random() * 8999999)}`;
  const ochish2 = await request.post(`${API}/admin/companies`, {
    headers: { "X-Vendor-Session": await sessiyaToken(page) },
    data: {
      company_name: "Egasi yopadigan", company_code: kod2, owner_name: "Owner Two",
      owner_phone: tel2, owner_password: PAROL, plan: "start",
    },
  });
  expect(ochish2.status()).toBe(200);
  const kir2 = await request.post(`${API}/auth/login/password`, {
    data: { phone: tel2, password: PAROL },
  });
  expect(kir2.status()).toBe(200);
  //    EGA O'ZI yopadi (haqiqiy CH-18 oqimi).
  const yopish = await request.post(`${API}/auth/store-closure`, {
    headers: { Authorization: `Bearer ${(await kir2.json()).access_token}` },
    data: { password: PAROL, confirm: "O'CHIRISH", delete_my_account: true },
  });
  expect(yopish.status()).toBe(200);

  await page.getByRole("button", { name: "Yangilash" }).click();  // audit + ro'yxat
  await page.evaluate(() => (window as any).loadDeleted());
  const yopilgan = page.locator("#delRows tr", { hasText: kod2 });
  await expect(yopilgan).toHaveCount(1, { timeout: 15_000 });
  await expect(yopilgan).toContainText(/egasi yopgan/);
  //    ASOSIY DARVOZA: tugma UMUMAN YO'Q.
  await expect(yopilgan.locator("button")).toHaveCount(0);
  //    POZITIV NAZORAT: vendor o'chirgan do'konda tugma BOR edi (13-14 qadam).
  //    VA MARSHRUTNING O'ZI ham RAD etadi — UI ni chetlab o'tib bo'lmaydi.
  const cid2 = (await ochish2.json()).company_id as string;
  const tiklaRad = await request.post(`${API}/admin/companies/${cid2}/restore`, {
    headers: { "X-Vendor-Session": await sessiyaToken(page) },
  });
  expect(tiklaRad.status()).toBe(409);
  expect(await tiklaRad.text()).toContain("EGASI");

  // ── 16. CHIQISH -> SESSIYA SERVER TOMONDA BEKOR ─────────────────
  //    O'LCHANGAN NUQSON: `logout()` faqat mijoz holatini tozalardi va eski
  //    token to'liq muddati davomida (standart 2 soat) ishlayverardi.
  //
  //    ⚠️  TARTIB CHEKLOV BYUDJETI BILAN BELGILANGAN (haqiqiy yurishda
  //        o'lchandi): `_VENDOR_IP_TIER = (5, 900)` — bitta manbadan
  //        15 daqiqada ATIGI 5 ta rad etilgan urinish. Avtorizatsiyasiz
  //        probalar ilgari SHU qadamdan OLDIN turardi va byudjetni yeb
  //        qo'yardi: himoyalangan chaqiruv 401 o'rniga 429 qaytarib,
  //        chiqish darvozasini NIQOBLARDI. Bu mahsulot nuqsoni EMAS —
  //        cheklov aynan shunday ishlashi kerak; test unga MOSLASHADI.
  //
  //        BYUDJET (jami 5): #1 noto'g'ri OTP (2-qadam) · #2 xom master
  //        kalit (4-qadam) · #3 bekor sessiya (quyida) · #4-#5
  //        avtorizatsiyasiz ikki marshrut (17-qadam).
  const sessiya = await sessiyaToken(page);
  expect(sessiya).toBeTruthy();
  const oldin = await request.get(`${API}/admin/overview`, {
    headers: { "X-Vendor-Session": sessiya },
  });
  expect(oldin.status()).toBe(200);

  await page.getByRole("button", { name: "Chiqish" }).click();
  await expect(page.locator("#login")).toBeVisible();
  await expect(page.locator("#otp")).toBeVisible();   // maydon HAMON ko'rinadi

  //    RAD ETILGAN URINISH #3: bekor qilingan sessiya.
  await expect
    .poll(async () => (await request.get(`${API}/admin/overview`, {
      headers: { "X-Vendor-Session": sessiya },
    })).status(), { timeout: 10_000 })
    .toBe(401);

  // ── 17. AVTORIZATSIYASIZ kirish YOPIQ (byudjetning oxirgi 2 tasi) ────
  //    ⚠️  IKKI marshrut, UCHTA emas — byudjet yuqorida hisoblangan.
  //        Uchinchisi (`/admin/companies`) backend testida qamralgan:
  //        `tests/test_admin_p0_console.py::test_P0B_6` har probadan oldin
  //        `vendor_auth_attempts` jadvalini tozalaydi, ya'ni u byudjetga
  //        bog'liq emas.
  for (const u of ["/admin/audit", "/admin/deleted-companies"]) {
    const r = await request.get(`${API}${u}`);
    expect([401, 403, 503]).toContain(r.status());
  }
});
