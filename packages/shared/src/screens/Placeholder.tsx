export function Placeholder({ title, sub }: { title: string; sub?: string }) {
  return (
    <main className="main">
      <div className="topbar">
        <div>
          <div className="h1">{title}</div>
          {sub && <div className="sub">{sub}</div>}
        </div>
      </div>
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", color: "var(--muted)" }}>
        <div style={{ fontSize: 40 }}>🚧</div>
        <div style={{ fontSize: 15, fontWeight: 600, marginTop: 10 }}>Bu ekran keyingi bosqichda ulanadi</div>
        <div style={{ fontSize: 13, marginTop: 4 }}>Dizayn tayyor · API endpointlari mavjud</div>
      </div>
    </main>
  );
}
