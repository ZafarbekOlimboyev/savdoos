import { useAuth } from "@/store/auth";

// Tayyor .exe (production) — Railway serveriga avto ulanadi, mijoz hech narsa sozlamaydi.
// Dev rejimda — lokal backend (run.bat). VITE_API_URL bilan istalganini bekor qilish mumkin.
const PROD_SERVER = "https://savdoos-production.up.railway.app";
const DEFAULT_ORIGIN =
  (import.meta as any).env?.VITE_API_URL ||
  ((import.meta as any).env?.DEV ? "http://localhost:8000" : PROD_SERVER);

// Server manzili — foydalanuvchi sozlaydi (localStorage), bitta .exe istalgan serverga ulanadi.
export function getServerUrl(): string {
  try {
    const u = localStorage.getItem("savdoos_api_url");
    if (u) return u;
  } catch {
    /* ignore */
  }
  return DEFAULT_ORIGIN;
}

export function setServerUrl(url: string): void {
  try {
    localStorage.setItem("savdoos_api_url", url.trim().replace(/\/+$/, ""));
  } catch {
    /* ignore */
  }
}

// Do'kon kodi — qurilma bitta do'konga bog'lanadi; PIN login faqat shu doirada tekshiriladi.
export function getCompanyCode(): string {
  try {
    return localStorage.getItem("savdoos_company_code") || "";
  } catch {
    return "";
  }
}

export function setCompanyCode(code: string): void {
  try {
    localStorage.setItem("savdoos_company_code", code.trim().toLowerCase());
  } catch {
    /* ignore */
  }
}

function base(): string {
  return getServerUrl().replace(/\/+$/, "") + "/api/v1";
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = useAuth.getState().token;
  const res = await fetch(base() + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    useAuth.getState().logout();
    throw new Error("Sessiya tugadi — qayta kiring");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null as T;
  return res.json();
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body: unknown) =>
  api<T>(p, { method: "POST", body: JSON.stringify(body) });
export const put = <T = any>(p: string, body: unknown) =>
  api<T>(p, { method: "PUT", body: JSON.stringify(body) });
export const patch = <T = any>(p: string, body: unknown) =>
  api<T>(p, { method: "PATCH", body: JSON.stringify(body) });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });
