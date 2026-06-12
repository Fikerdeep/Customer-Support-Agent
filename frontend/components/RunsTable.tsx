"use client";

import { RunRow, decisionClass } from "@/lib/api";

function shorten(s: string, n = 48): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function timeOnly(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString();
}

export default function RunsTable({
  runs,
  selectedId,
  onSelect,
}: {
  runs: RunRow[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  if (runs.length === 0) {
    return <div className="muted">No runs yet — send a message from the Customer Chat tab.</div>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Time</th>
          <th>Customer</th>
          <th>Decision</th>
          <th>Message</th>
          <th>Turns</th>
          <th>Tools</th>
          <th>Retries</th>
          <th>Tokens</th>
          <th>Cost</th>
          <th>Latency</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => (
          <tr
            key={r.id}
            className={`clickable ${selectedId === r.id ? "selected" : ""}`}
            onClick={() => onSelect(r.id)}
          >
            <td>{r.id}</td>
            <td>{timeOnly(r.created_at)}</td>
            <td>{r.customer_name}</td>
            <td>
              <span className={decisionClass(r.decision)}>{r.decision}</span>
            </td>
            <td>
              {shorten(r.user_message)}
              {r.injection_flagged && (
                <span className="flag bad" title={(r.injection_tags ?? []).join(", ")}>
                  ⚠ injection
                </span>
              )}
            </td>
            <td>{r.num_llm_turns}</td>
            <td>{r.num_tool_calls}</td>
            <td style={{ color: r.num_retries > 0 ? "var(--red)" : undefined }}>{r.num_retries}</td>
            <td>
              {r.total_input_tokens}+{r.total_output_tokens}
            </td>
            <td>${r.total_cost_usd.toFixed(6)}</td>
            <td>{Math.round(r.total_latency_ms)}ms</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
