export function fmt(n: number): string {
  const v = Math.round(n || 0);
  return new Intl.NumberFormat("ru-RU").format(v).replace(/,/g, " ") + " so'm";
}

export function fmtShort(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " mln";
  if (n >= 1e3) return Math.round(n / 1e3) + " ming";
  return String(Math.round(n || 0));
}
