"use client";

import { useCallback, useEffect, useState } from "react";
import { Escalation, getEscalations, resolveEscalation } from "@/lib/api";

export default function EscalationsPanel({
  reloadKey,
  onResolved,
}: {
  reloadKey: number;
  onResolved: () => void;
}) {
  const [rows, setRows] = useState<Escalation[]>([]);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await getEscalations());
    } catch {
      setRows([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  async function act(id: number, action: "approve" | "deny") {
    setBusy(id);
    try {
      await resolveEscalation(id, action);
      await load();
      onResolved();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 18 }}>
      <h3>Human review queue — escalated refunds (&gt; $500)</h3>
      {rows.length === 0 ? (
        <div className="muted">No refunds awaiting human review.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Order</th>
              <th>Customer</th>
              <th>Amount</th>
              <th>Reason</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.refund_id}>
                <td>{e.order_number}</td>
                <td>{e.customer_name}</td>
                <td>${e.amount.toFixed(2)}</td>
                <td>{e.reason}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button
                    onClick={() => act(e.refund_id, "approve")}
                    disabled={busy === e.refund_id}
                    style={{ marginRight: 6 }}
                  >
                    Approve
                  </button>
                  <button
                    className="ghost"
                    onClick={() => act(e.refund_id, "deny")}
                    disabled={busy === e.refund_id}
                  >
                    Deny
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
