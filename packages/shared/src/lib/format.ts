import { useLang } from "@/store/lang";

// Valyuta belgisi tilga qarab: uz → so'm, ru/ky → сом (Qirg'iziston).
// TODO: kelajakda do'kon sozlamasidan (company.currency) olinsa yanada aniq bo'ladi.
const CUR: Record<string, string> = { uz: "so'm", uzc: "сўм", ru: "сом", ky: "сом" };

export function fmt(n: number): string {
  const v = Math.round(n || 0);
  const cur = CUR[useLang.getState().lang] || "сом";
  return new Intl.NumberFormat("ru-RU").format(v).replace(/,/g, " ") + " " + cur;
}

export function fmtShort(n: number): string {
  const lang = useLang.getState().lang;
  const mln = lang === "uz" ? "mln" : "млн";
  const ming = lang === "ru" ? "тыс" : lang === "ky" ? "миң" : lang === "uzc" ? "минг" : "ming";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " " + mln;
  if (n >= 1e3) return Math.round(n / 1e3) + " " + ming;
  return String(Math.round(n || 0));
}
