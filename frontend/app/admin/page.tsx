"use client";

import { useEffect, useState } from "react";
import EscalationsPanel from "@/components/EscalationsPanel";
import RunsTable from "@/components/RunsTable";
import TraceViewer from "@/components/TraceViewer";
import { RunDetail, RunRow, Stats, getRun, getRuns, getStats } from "@/lib/api";

export default function AdminPage() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<RunDetail | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  async function refresh() {
    const [r, s] = await Promise.all([getRuns(), getStats()]);
    setRuns(r);
    setStats(s);
    setReloadKey((k) => k + 1);
  }

  useEffect(() => {
    refresh().catch(() => {});
  }, []);

  async function select(id: number) {
    setSelectedId(id);
    try {
      setSelected(await getRun(id));
    } catch {
      setSelected(null);
    }
  }

  const d = stats?.by_decision ?? {};

  return (
    <div className="container">
      <div className="stat-row">
        <div className="stat">
          <div className="v">{stats?.total_runs ?? 0}</div>
          <div className="k">Agent runs</div>
        </div>
        <div className="stat">
          <div className="v" style={{ color: "var(--green)" }}>{d.approved ?? 0}</div>
          <div className="k">Approved</div>
        </div>
        <div className="stat">
          <div className="v" style={{ color: "var(--red)" }}>{d.denied ?? 0}</div>
          <div className="k">Denied</div>
        </div>
        <div className="stat">
          <div className="v" style={{ color: "var(--amber)" }}>{d.escalated ?? 0}</div>
          <div className="k">Escalated</div>
        </div>
        <div className="stat">
          <div className="v">${(stats?.total_cost_usd ?? 0).toFixed(4)}</div>
          <div className="k">Total spend</div>
        </div>
        <div className="stat">
          <div className="v" style={{ color: (stats?.injection_attempts ?? 0) > 0 ? "var(--red)" : undefined }}>
            {stats?.injection_attempts ?? 0}
          </div>
          <div className="k">Injection attempts</div>
        </div>
        <div className="stat">
          <div className="v" style={{ color: (stats?.pending_escalations ?? 0) > 0 ? "var(--amber)" : undefined }}>
            {stats?.pending_escalations ?? 0}
          </div>
          <div className="k">Awaiting review</div>
        </div>
      </div>

      <EscalationsPanel reloadKey={reloadKey} onResolved={() => refresh().catch(() => {})} />

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Agent runs — reasoning &amp; trace logs</h3>
          <button className="ghost" onClick={() => refresh().catch(() => {})}>
            Refresh
          </button>
        </div>
        <RunsTable runs={runs} selectedId={selectedId} onSelect={select} />
      </div>

      <TraceViewer run={selected} />
    </div>
  );
}
