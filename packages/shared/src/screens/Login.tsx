import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getServerUrl, post, setServerUrl } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useLang, LANGS } from "@/store/lang";
import { useT } from "@/lib/i18n";

export function Login() {
  const [pin, setPin] = useState("");
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

  async function submit(value: string) {
    setBusy(true);
    setErr("");
    try {
      const res = await post("/auth/login", { pin: value });
      setAuth(res.access_token, res.employee);
      nav("/");
    } catch (e: any) {
      setErr(e.message || t("common.error"));
      setPin("");
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
      if (next.length === 4) submit(next);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div style={{ width: 52, height: 52, borderRadius: 14, background: "var(--accent)", color: "#fff",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, fontWeight: 700, margin: "0 auto 14px" }}>S</div>
        <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.02em" }}>SavdoOS</div>
        <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>{t("login.enterPin")}</div>

        <div style={{ display: "flex", gap: 6, justifyContent: "center", marginTop: 14 }}>
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

        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 18 }}>{t("login.demo")}</div>

        <button onClick={() => setShowServer((v) => !v)} style={{ marginTop: 14, border: "none", background: "none", cursor: "pointer", color: "var(--muted)", fontSize: 12 }}>
          {t("login.serverSettings")}
        </button>
        {showServer && (
          <div style={{ marginTop: 10, textAlign: "left" }}>
            <label style={{ fontSize: 11.5, color: "var(--text3)", fontWeight: 600 }}>{t("login.serverAddr")}</label>
            <input value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://api.mydomain.com"
              style={{ width: "100%", height: 42, padding: "0 12px", border: "1.5px solid var(--border-input)", borderRadius: 10, fontSize: 13, outline: "none", boxSizing: "border-box", marginTop: 6, background: "var(--card)", color: "var(--text)" }} />
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
