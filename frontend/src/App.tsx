import { useEffect, useState } from "react";

interface Health {
  status: string;
  db: string;
  redis: string;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const poll = () =>
      fetch("/api/health")
        .then((r) => r.json())
        .then((h: Health) => {
          setHealth(h);
          setError(false);
        })
        .catch(() => setError(true));
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const healthy = !error && health?.status === "ok";
  const color = error || (health && health.status !== "ok") ? "#d33" : healthy ? "#2a2" : "#999";
  const label = error
    ? "backend unreachable"
    : health
      ? `backend ${health.status} (db: ${health.db}, redis: ${health.redis})`
      : "checking…";

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "4rem", textAlign: "center" }}>
      <h1>FlowForge-AI</h1>
      <p>
        <span
          style={{
            display: "inline-block",
            width: 12,
            height: 12,
            borderRadius: "50%",
            background: color,
            marginRight: 8,
          }}
        />
        {label}
      </p>
    </main>
  );
}
