import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getServerUrl, post, setServerUrl } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useLang, LANGS } from "@/store/lang";
import { useT } from "@/lib/i18n";

// POS (kassir) login — PIN-pad asosiy, parol (admin) zaxira. PIN ko'p-tenant'да
// do'kon kodini talab qiladi (bir marta sozlanadi, saqlanadi).
const CC_KEY = "savdoos-company-code";
const PREFIX = "+996 ";

export function LoginPin() {
  const [pin, setPin] = useState("");
  const [mode, setMode] = useState<"pin" | "password">("pin");
  const [company, setCompany] = useState(() => localStorage.getItem(CC_KEY) || "");
  const [phone, setPhone] = useState(PREFIX);
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [cfg, setCfg] = useState(false);
  const [server, setServer] = useState(getServerUrl());
  const setAuth = useAuth((s) => s.setAuth);
  const nav = useNavigate();
  const { lang, set: setLang } = useLang();
  const t = useT();

  function saveCfg() {
    setServerUrl(server);
    localStorage.setItem(CC_KEY, company.trim());
    setCfg(false); setErr("");
  }

  async function submitPin(full: string) {
    setBusy(true); setErr("");
    try {
      const body: any = { pin: full };
      if (company.trim()) body.company_code = company.trim();
      const res = await post("/auth/login", body);
      setAuth(res.access_token, res.employee);
      nav("/");
    } catch (e: any) {
      setErr(e.message || t("common.error")); setPin("");
    } finally { setBusy(false); }
  }
  function digit(n: number) {
    if (busy || pin.length >= 4) return;
    const next = pin + n;
    setErr(""); setPin(next);
    if (next.length === 4) submitPin(next);
  }
  function back() { if (!busy) setPin((p) => p.slice(0, -1)); }

  async function submitPw() {
    const ph = phone.trim();
    if (!ph || ph === PREFIX.trim() || !password || busy) return;
    setBusy(true); setErr("");
    try {
      const res = await post("/auth/login/password", { phone: ph, password });
      setAuth(res.access_token, res.employee);
      nav("/");
    } catch (e: any) { setErr(e.message || t("common.error")); setPassword(""); }
    finally { setBusy(false); }
  }

  const KEY: React.CSSProperties = { height: 62, borderRadius: 16, background: "var(--card)", border: "1px solid var(--border)", cursor: "pointer", fontSize: 26, fontWeight: 600, color: "var(--text)", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 2px 6px rgba(28,31,43,0.04)" };

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", background: "var(--bg)", color: "var(--text)", position: "relative" }}>
      {/* config gear */}
      <button onClick={() => setCfg((v) => !v)} title={t("login.serverSettings")} style={{ position: "absolute", top: 20, right: 20, border: "none", background: "none", cursor: "pointer", color: "var(--muted)", padding: 6, display: "flex" }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 0 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H10a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V10a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>
      </button>

      <div style={{ width: 42, height: 42, borderRadius: 13, background: "var(--accent)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 21, fontWeight: 800, marginBottom: 12 }}>S</div>

      {cfg ? (
        <div style={{ width: 300, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 16, padding: 20 }}>
          <div style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600, marginBottom: 6 }}>{t("login.companyCode")}</div>
          <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="do'kon kodi" autoCapitalize="off"
            style={{ width: "100%", height: 42, padding: "0 13px", border: "1.5px solid var(--border-input)", borderRadius: 11, fontSize: 14, boxSizing: "border-box", background: "var(--bg)", color: "var(--text)", outline: "none" }} />
          <div style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600, margin: "12px 0 6px" }}>{t("login.serverAddr")}</div>
          <input value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://api..."
            style={{ width: "100%", height: 42, padding: "0 13px", border: "1.5px solid var(--border-input)", borderRadius: 11, fontSize: 13.5, boxSizing: "border-box", background: "var(--bg)", color: "var(--text)", outline: "none" }} />
          <button className="btn btn-primary" style={{ width: "100%", marginTop: 14, padding: "10px 0" }} onClick={saveCfg}>{t("common.save")}</button>
        </div>
      ) : mode === "pin" ? (
        <>
          <div style={{ fontSize: 15, color: "var(--muted)" }}>{t("login.enterPin")}</div>
          <div style={{ display: "flex", gap: 14, marginTop: 22 }}>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} style={{ width: 14, height: 14, borderRadius: "50%", background: i < pin.length ? "var(--accent)" : "transparent", border: i < pin.length ? "none" : "2px solid var(--border-input)" }} />
            ))}
          </div>
          <div style={{ height: 20, marginTop: 10, color: "var(--red)", fontSize: 13, fontWeight: 600 }}>{err}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 74px)", gap: 12, marginTop: 6 }}>
            {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
              <button key={n} style={KEY} onClick={() => digit(n)}>{n}</button>
            ))}
            <div />
            <button style={KEY} onClick={() => digit(0)}>0</button>
            <button style={{ ...KEY, background: "transparent", border: "none", boxShadow: "none" }} onClick={back}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z" /><path d="M18 9l-6 6M12 9l6 6" /></svg>
            </button>
          </div>
          <button onClick={() => { setMode("password"); setErr(""); }} style={{ marginTop: 24, border: "none", background: "none", cursor: "pointer", fontSize: 13.5, color: "var(--accent-strong)", fontWeight: 600 }}>{t("login.byPassword")}</button>
        </>
      ) : (
        <div style={{ width: 320 }}>
          <div style={{ fontSize: 18, fontWeight: 800, textAlign: "center", marginBottom: 4 }}>{t("login.adminEntry")}</div>
          <div style={{ fontSize: 13, color: "var(--muted)", textAlign: "center", marginBottom: 18 }}>{t("login.signInTitle")}</div>
          <form onSubmit={(e) => { e.preventDefault(); submitPw(); }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, height: 48, padding: "0 14px", border: "1.5px solid var(--border-input)", borderRadius: 12, background: "var(--card)" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3-8.6A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z" /></svg>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus inputMode="tel" style={{ flex: 1, border: "none", outline: "none", background: "transparent", color: "var(--text)", fontSize: 15 }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, height: 48, padding: "0 14px", marginTop: 12, border: "1.5px solid var(--accent)", borderRadius: 12, background: "var(--card)" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
              <input value={password} onChange={(e) => setPassword(e.target.value)} type={showPw ? "text" : "password"} style={{ flex: 1, border: "none", outline: "none", background: "transparent", color: "var(--text)", fontSize: 15 }} />
              <button type="button" onClick={() => setShowPw((v) => !v)} style={{ border: "none", background: "none", cursor: "pointer", padding: 0, display: "flex" }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></svg>
              </button>
            </div>
            {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10, textAlign: "center" }}>{err}</div>}
            <button type="submit" disabled={busy} style={{ width: "100%", height: 50, marginTop: 18, borderRadius: 12, border: "none", cursor: "pointer", background: "var(--accent)", color: "#fff", fontSize: 15.5, fontWeight: 700 }}>{busy ? "..." : t("login.signIn")}</button>
          </form>
          <button onClick={() => { setMode("pin"); setErr(""); }} style={{ width: "100%", marginTop: 16, border: "none", background: "none", cursor: "pointer", fontSize: 13.5, color: "var(--accent-strong)", fontWeight: 600 }}>{t("login.byPin")}</button>
        </div>
      )}

      {!cfg && (
        <div style={{ position: "absolute", bottom: 22, display: "flex", gap: 6 }}>
          {LANGS.map((l) => (
            <button key={l.code} onClick={() => setLang(l.code)} style={{ padding: "5px 11px", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 12, fontWeight: 600,
              border: `1.5px solid ${lang === l.code ? "var(--accent)" : "var(--border-input)"}`, background: lang === l.code ? "var(--accent-soft)" : "var(--card)", color: lang === l.code ? "var(--accent-strong)" : "var(--text3)" }}>{l.native}</button>
          ))}
        </div>
      )}
    </div>
  );
}
