"use client";

import { RunDetail, TraceEvent, decisionClass } from "@/lib/api";

function pretty(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

function LlmEvent({ e }: { e: TraceEvent }) {
  return (
    <div className="trace-event llm">
      <div className="head">
        <span className="title">🧠 LLM turn (step {e.step})</span>
        <span className="metrics">
          in {e.input_tokens} · out {e.output_tokens} · {Math.round(e.latency_ms ?? 0)}ms · $
          {Number(e.cost_usd ?? 0).toFixed(6)}
          {e.stop_reason ? ` · ${e.stop_reason}` : ""}
        </span>
      </div>
      {e.reasoning && <div className="reasoning">{e.reasoning}</div>}
      {e.text && <div>{e.text}</div>}
      {e.tool_calls && e.tool_calls.length > 0 && (
        <pre className="io">
          → calls: {e.tool_calls.map((tc) => `${tc.name}(${pretty(tc.args)})`).join("\n          ")}
        </pre>
      )}
    </div>
  );
}

function ToolEvent({ e }: { e: TraceEvent }) {
  const bad = e.is_retry_trigger || !e.ok;
  return (
    <div className={`trace-event tool ${bad ? "bad" : ""}`}>
      <div className="head">
        <span className="title">
          🔧 {e.name} (step {e.step}){" "}
          {bad && <span className="retry-pill">FAILED · TRIGGERS RETRY</span>}
        </span>
        <span className="metrics">{Math.round(e.latency_ms ?? 0)}ms</span>
      </div>
      <pre className="io">
        <strong>input</strong>: {pretty(e.input)}
      </pre>
      <pre className="io">
        <strong>output</strong>: {pretty(e.output)}
      </pre>
      {e.error && (
        <pre className="io" style={{ color: "var(--red)" }}>
          <strong>error</strong>: {e.error}
        </pre>
      )}
    </div>
  );
}

export default function TraceViewer({ run }: { run: RunDetail | null }) {
  if (!run) {
    return (
      <div className="card">
        <h3>Run trace</h3>
        <div className="muted">Select a run from the table to replay its full trace.</div>
      </div>
    );
  }
  const s = run.trace?.summary ?? {};
  const events = run.trace?.events ?? [];
  return (
    <div className="card">
      <div className="head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div>
          <strong>Run #{run.id}</strong> · {run.customer_name}{" "}
          <span className={decisionClass(run.decision)}>{run.decision}</span>
        </div>
        <span className="metrics">
          {s.total_input_tokens}+{s.total_output_tokens} tok · ${Number(s.total_cost_usd ?? 0).toFixed(6)} ·{" "}
          {s.total_latency_ms}ms · {s.num_llm_turns} turns · {s.num_tool_calls} tools · {s.num_retries} retries
        </span>
      </div>
      <pre className="io">
        <strong>User:</strong> {run.user_message}
      </pre>
      {events.map((e, i) => (e.type === "llm" ? <LlmEvent key={i} e={e} /> : <ToolEvent key={i} e={e} />))}
      <pre className="io">
        <strong>Final reply:</strong> {run.final_reply}
      </pre>
    </div>
  );
}
