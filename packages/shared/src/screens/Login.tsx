import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getCompanyCode, getServerUrl, post, setCompanyCode, setServerUrl } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useLang, LANGS } from "@/store/lang";
import { useT } from "@/lib/i18n";

type Mode = "pin" | "password";

const inputStyle: React.CSSProperties = {
  width: "100%", height: 42, padding: "0 12px", border: "1.5px solid var(--border-input)",
  borderRadius: 10, fontSize: 13, outline: "none", boxSizing: "border-box", marginTop: 6,
  background: "var(--card)", color: "var(--text)",
};

export function Login() {
  const [mode, setMode] = useState<Mode>("pin");
  const [pin, setPin] = useState("");
  const [code, setCode] = useState(getCompanyCode());
  const [needCode, setNeedCode] = useState(false);
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [showServer, setShowServer] = useState(false);
  const [server, setServer] = useState(getServerUrl());
  const [savedMsg, setSavedMsg] = useState("");
  const setAuth = useAuth((s) => s.setAuth);
  const nav = useNavigate();
  const { lang, set: setLang } = useLang();
  const t = useT();

  function saveServer() {
    setServerUrl(server);
    setSavedMsg(t("login.saved"));
    setTimeout(() => setSavedMsg(""), 2000);
  }

  function saveCode(v: string) {
    setCode(v);
    setCompanyCode(v);
  }

  async function submitPin(value: string) {
    setBusy(true);
    setErr("");
    try {
      const cc = code.trim().toLowerCase();
      const res = await post("/auth/login", { pin: value, ...(cc ? { company_code: cc } : {}) });
      setAuth(res.access_token, res.employee);
      nav("/");
    } catch (e: any) {
      const msg = e.message || t("common.error");
      // Server ko'p do'konli bo'lsa — do'kon kodi majburiy; maydonni ochamiz.
      if (String(msg).includes("company_code") || String(msg).includes("Do'kon kodi")) setNeedCode(true);
      setErr(msg);
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  async function submitPassword() {
    if (!phone.trim() || !password) return;
    setBusy(true);
    setErr("");
    try {
      const res = await post("/auth/login/password", { phone: phone.trim(), password });
      setAuth(res.access_token, res.employee);
      nav("/");
    } catch (e: any) {
      setErr(e.message || t("common.error"));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  function press(d: string) {
    if (busy) return;
    if (d === "del") return setPin((p) => p.slice(0, -1));
    const next = (pin + d).slice(0, 6);
    setPin(next);
    if (next.length >= 4 && d !== "del") {
      // 4 xonaga yetganda avtomatik urinib ko'rish
      if (next.length === 4) submitPin(next);
    }
  }

  const tabStyle = (on: boolean): React.CSSProperties => ({
    flex: 1, padding: "9px 10px", borderRadius: 10, cursor: "pointer", font: "inherit",
    fontSize: 13, fontWeight: 700,
    border: `1.5px solid ${on ? "var(--accent)" : "var(--border-input)"}`,
    background: on ? "var(--accent-soft)" : "var(--card)",
    color: on ? "var(--accent-strong)" : "var(--text3)",
  });

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div style={{ width: 52, height: 52, borderRadius: 14, background: "var(--accent)", color: "#fff",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, fontWeight: 700, margin: "0 auto 14px" }}>S</div>
        <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.02em" }}>SavdoOS</div>

        <div style={{ display: "flex", gap: 6, justifyContent: "center", marginTop: 12 }}>
          {LANGS.map((l) => (
            <button key={l.code} onClick={() => setLang(l.code)}
              style={{ padding: "6px 14px", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 12.5, fontWeight: 600,
                border: `1.5px solid ${lang === l.code ? "var(--accent)" : "var(--border-input)"}`,
                background: lang === l.code ? "var(--accent-soft)" : "var(--card)",
                color: lang === l.code ? "var(--accent-strong)" : "var(--text3)" }}>
              {l.native}
            </button>
          ))}
        </div>

        {/* Rejim: kassir PIN / egа parol */}
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button style={tabStyle(mode === "pin")} onClick={() => { setMode("pin"); setErr(""); }}>
            {t("login.tabPin")}
          </button>
          <button style={tabStyle(mode === "password")} onClick={() => { setMode("password"); setErr(""); }}>
            {t("login.tabPassword")}
          </button>
        </div>

        {mode === "pin" ? (
          <>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 12 }}>{t("login.enterPin")}</div>

            {(needCode || code) && (
              <div style={{ marginTop: 10, textAlign: "left" }}>
                <label style={{ fontSize: 11.5, color: "var(--text3)", fontWeight: 600 }}>{t("login.storeCode")}</label>
                <input value={code} onChange={(e) => saveCode(e.target.value)} placeholder="mening-dokonim"
                  style={inputStyle} />
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{t("login.storeCodeHint")}</div>
              </div>
            )}

            <div className="pin-dots">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className={"pin-dot" + (i < pin.length ? " on" : "")} />
              ))}
            </div>

            {err && <div style={{ color: "var(--red)", fontSize: 13, marginBottom: 12 }}>{err}</div>}

            <div className="pin-grid">
              {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => (
                <button key={d} className="pin-key" onClick={() => press(d)}>{d}</button>
              ))}
              <div />
              <button className="pin-key" onClick={() => press("0")}>0</button>
              <button className="pin-key" onClick={() => press("del")}>⌫</button>
            </div>

            {!needCode && !code && (
              <button onClick={() => setNeedCode(true)}
                style={{ marginTop: 12, border: "none", background: "none", cursor: "pointer", color: "var(--muted)", fontSize: 12 }}>
                {t("login.storeCode")}
              </button>
            )}

            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 12 }}>{t("login.demo")}</div>
          </>
        ) : (
          <form style={{ marginTop: 14, textAlign: "left" }}
            onSubmit={(e) => { e.preventDefault(); submitPassword(); }}>
            <label style={{ fontSize: 11.5, color: "var(--text3)", fontWeight: 600 }}>{t("login.phone")}</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+996 700 000 000"
              autoFocus style={inputStyle} />
            <label style={{ fontSize: 11.5, color: "var(--text3)", fontWeight: 600, display: "block", marginTop: 10 }}>
              {t("login.password")}
            </label>
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password"
              style={inputStyle} />
            {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
            <button type="submit" className="btn btn-primary" disabled={busy || !phone.trim() || !password}
              style={{ width: "100%", marginTop: 14, padding: "11px 0", fontSize: 14.5 }}>
              {busy ? "..." : t("login.signIn")}
            </button>
          </form>
        )}

        <button onClick={() => setShowServer((v) => !v)} style={{ marginTop: 14, border: "none", background: "none", cursor: "pointer", color: "var(--muted)", fontSize: 12 }}>
          {t("login.serverSettings")}
        </button>
        {showServer && (
          <div style={{ marginTop: 10, textAlign: "left" }}>
            <label style={{ fontSize: 11.5, color: "var(--text3)", fontWeight: 600 }}>{t("login.serverAddr")}</label>
            <input value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://api.mydomain.com"
              style={inputStyle} />
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
              <button className="btn btn-primary" style={{ padding: "8px 16px", fontSize: 13 }} onClick={saveServer}>{t("common.save")}</button>
              <button style={{ border: "none", background: "none", cursor: "pointer", color: "var(--muted)", fontSize: 12 }} onClick={() => { setServer("http://localhost:8000"); setServerUrl("http://localhost:8000"); }}>{t("login.local")}</button>
              {savedMsg && <span style={{ fontSize: 12, color: "var(--green)" }}>{savedMsg}</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
