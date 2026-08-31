import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getServerUrl, post, setServerUrl } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useLang, LANGS } from "@/store/lang";
import { useT } from "@/lib/i18n";

// Manager login — "brend paneli" (chapda gradient + afzalliklar, o'ngda forma).
const PREFIX = "+996 ";

export function LoginBrand() {
  const [phone, setPhone] = useState(PREFIX);
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [showServer, setShowServer] = useState(false);
  const [server, setServer] = useState(getServerUrl());
  const [savedMsg, setSavedMsg] = useState("");
  const setAuth = useAuth((s) => s.setAuth);
  const nav = useNavigate();
  const { lang, set: setLang } = useLang();
  const t = useT();

  const phoneClean = () => phone.trim();
  function saveServer() {
    setServerUrl(server);
    setSavedMsg(t("login.saved"));
    setTimeout(() => setSavedMsg(""), 2000);
  }
  async function submit() {
    const ph = phoneClean();
    if (!ph || ph === PREFIX.trim() || !password || busy) return;
    setBusy(true); setErr("");
    try {
      const res = await post("/auth/login/password", { phone: ph, password });
      setAuth(res.access_token, res.employee);
      nav("/");
    } catch (e: any) {
      setErr(e.message || t("common.error"));
      setPassword("");
    } finally { setBusy(false); }
  }

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex", background: "var(--bg)", color: "var(--text)", overflow: "hidden" }}>
      {/* LEFT brand panel */}
      <div style={{ width: "44%", flex: "none", padding: "clamp(32px,5vw,60px)", background: "linear-gradient(150deg, #7060e0 0%, #5a4bc4 62%, #4a3ea8 100%)", color: "#fff", display: "flex", flexDirection: "column", justifyContent: "space-between", position: "relative" }} className="login-brand-panel">
        <div style={{ position: "absolute", right: -80, top: -80, width: 300, height: 300, borderRadius: "50%", background: "rgba(255,255,255,0.07)" }} />
        <div style={{ position: "absolute", right: 40, bottom: 150, width: 150, height: 150, borderRadius: "50%", background: "rgba(255,255,255,0.06)" }} />
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 46, height: 46, borderRadius: 14, background: "rgba(255,255,255,0.16)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 23, fontWeight: 800 }}>S</div>
          <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-0.02em" }}>SavdoOS</div>
        </div>
        <div>
          <div style={{ fontSize: "clamp(24px,2.6vw,34px)", fontWeight: 800, lineHeight: 1.2, letterSpacing: "-0.02em", maxWidth: 360 }}>{t("login.heroTitle")}</div>
          <div style={{ fontSize: 15, color: "rgba(255,255,255,0.82)", marginTop: 14, maxWidth: 330, lineHeight: 1.55 }}>{t("login.heroSub")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 30 }}>
            {[
              [<path key="a" d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.3 2.3A1 1 0 0 0 5.4 17H17" />, t("login.feat1")],
              [<><path key="b" d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" /><path d="M3.3 7 12 12l8.7-5M12 22V12" /></>, t("login.feat2")],
              [<path key="c" d="M3 3v18h18M7 15l4-4 3 3 5-6" />, t("login.feat3")],
            ].map(([icon, label], i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ width: 34, height: 34, flex: "none", borderRadius: 10, background: "rgba(255,255,255,0.16)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{icon}</svg>
                </div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>{label as string}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ fontSize: 12.5, color: "rgba(255,255,255,0.6)" }}>© 2026 SavdoOS</div>
      </div>

      {/* RIGHT form */}
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 32 }}>
        <div style={{ width: "100%", maxWidth: 340 }}>
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.02em" }}>{t("login.welcome")}</div>
          <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 5 }}>{t("login.signInTitle")}</div>

          <form style={{ marginTop: 24 }} onSubmit={(e) => { e.preventDefault(); submit(); }}>
            <div style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600, marginBottom: 7 }}>{t("login.phone")}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, height: 48, padding: "0 14px", border: "1.5px solid var(--border-input)", borderRadius: 12, background: "var(--card)" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3-8.6A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z" /></svg>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus autoComplete="username" inputMode="tel"
                style={{ flex: 1, border: "none", outline: "none", background: "transparent", color: "var(--text)", fontSize: 15 }} />
            </div>

            <div style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600, margin: "14px 0 7px" }}>{t("login.password")}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, height: 48, padding: "0 14px", border: "1.5px solid var(--accent)", borderRadius: 12, background: "var(--card)" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
              <input value={password} onChange={(e) => setPassword(e.target.value)} type={showPw ? "text" : "password"} autoComplete="current-password"
                style={{ flex: 1, border: "none", outline: "none", background: "transparent", color: "var(--text)", fontSize: 15 }} />
              <button type="button" onClick={() => setShowPw((v) => !v)} style={{ border: "none", background: "none", cursor: "pointer", padding: 0, display: "flex" }} aria-label={t("login.togglePassword")}>
                {showPw
                  ? <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.9 17.9A10.4 10.4 0 0 1 12 20C5 20 2 12 2 12a19 19 0 0 1 5-6M9.9 4.2A9.5 9.5 0 0 1 12 4c7 0 10 8 10 8a19 19 0 0 1-2.2 3.2M1 1l22 22M9.9 9.9a3 3 0 1 0 4.2 4.2" /></svg>
                  : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></svg>}
              </button>
            </div>

            {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
            <button type="submit" disabled={busy} style={{ width: "100%", height: 50, marginTop: 22, borderRadius: 12, border: "none", cursor: "pointer", background: "var(--accent)", color: "#fff", fontSize: 15.5, fontWeight: 700, boxShadow: "0 8px 20px rgba(109,93,211,0.35)" }}>
              {busy ? "..." : t("login.signIn")}
            </button>
          </form>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 20 }}>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {LANGS.map((l) => (
                <button key={l.code} onClick={() => setLang(l.code)} style={{ padding: "6px 12px", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 12.5, fontWeight: 600,
                  border: `1.5px solid ${lang === l.code ? "var(--accent)" : "var(--border-input)"}`, background: lang === l.code ? "var(--accent-soft)" : "var(--card)", color: lang === l.code ? "var(--accent-strong)" : "var(--text3)" }}>{l.native}</button>
              ))}
            </div>
            <button onClick={() => setShowServer((v) => !v)} title={t("login.serverSettings")} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--muted)", padding: 4, display: "flex" }}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 0 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H10a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V10a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>
            </button>
          </div>

          {showServer && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11.5, color: "var(--text3)", fontWeight: 600 }}>{t("login.serverAddr")}</div>
              <input value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://api.mydomain.com"
                style={{ width: "100%", height: 42, padding: "0 13px", border: "1.5px solid var(--border-input)", borderRadius: 11, fontSize: 13.5, marginTop: 6, boxSizing: "border-box", background: "var(--card)", color: "var(--text)", outline: "none" }} />
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
                <button className="btn btn-primary" style={{ padding: "8px 16px", fontSize: 13 }} onClick={saveServer}>{t("common.save")}</button>
                {savedMsg && <span style={{ fontSize: 12, color: "var(--green)" }}>{savedMsg}</span>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
