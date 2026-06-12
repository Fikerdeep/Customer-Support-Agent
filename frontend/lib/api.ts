// Typed client for the Loopp backend. Calls are same-origin (/api/*) and proxied
// to FastAPI by the rewrite in next.config.mjs.

export interface Customer {
  id: number;
  name: string;
  email: string;
  loyalty_tier: string;
  lifetime_value: number;
  order_count: number;
}

export interface OrderItem {
  sku: string;
  product_name: string;
  category: string;
  quantity: number;
  unit_price: number;
  is_final_sale: boolean;
  is_returnable: boolean;
}

export interface Order {
  order_number: string;
  status: string;
  order_date: string | null;
  delivered_at: string | null;
  total_amount: number;
  currency: string;
  already_refunded: boolean;
  items: OrderItem[];
}

export interface ChatTurn {
  role: string;
  content: string;
}

export interface ChatResponse {
  reply: string;
  decision: string;
  run_id: number;
  session_id: string;
  summary: Record<string, number | string>;
}

export interface RunRow {
  id: number;
  session_id: string;
  customer_id: number | null;
  customer_name: string | null;
  created_at: string | null;
  decision: string;
  user_message: string;
  final_reply: string;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_latency_ms: number;
  num_llm_turns: number;
  num_tool_calls: number;
  num_retries: number;
  injection_flagged?: boolean;
  injection_tags?: string[];
}

export interface Escalation {
  refund_id: number;
  order_number: string | null;
  customer_name: string | null;
  amount: number;
  reason: string;
  policy_rule_applied: string;
  created_at: string | null;
}

export interface TraceEvent {
  type: "llm" | "tool";
  step: number;
  // llm
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cost_usd?: number;
  latency_ms?: number;
  stop_reason?: string | null;
  reasoning?: string | null;
  text?: string | null;
  tool_calls?: { name: string; args: Record<string, unknown> }[];
  // tool
  name?: string;
  input?: Record<string, unknown>;
  output?: unknown;
  ok?: boolean;
  error?: string | null;
  is_retry_trigger?: boolean;
}

export interface RunDetail {
  id: number;
  session_id: string;
  customer_name: string | null;
  created_at: string | null;
  decision: string;
  user_message: string;
  final_reply: string;
  trace: { summary: Record<string, number | string>; events: TraceEvent[] };
}

export interface Stats {
  total_runs: number;
  by_decision: Record<string, number>;
  total_cost_usd: number;
  customers: number;
  orders: number;
  injection_attempts: number;
  pending_escalations: number;
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const getCustomers = () => getJSON<Customer[]>("/api/customers");
export const getOrders = (customerId: number) =>
  getJSON<Order[]>(`/api/customers/${customerId}/orders`);
export const getRuns = () => getJSON<RunRow[]>("/api/runs");
export const getRun = (id: number) => getJSON<RunDetail>(`/api/runs/${id}`);
export const getStats = () => getJSON<Stats>("/api/stats");
export const getEscalations = () => getJSON<Escalation[]>("/api/escalations");

export async function resolveEscalation(
  refundId: number,
  action: "approve" | "deny",
  note = "",
): Promise<{ status: string; decided_by: string }> {
  const res = await fetch(`/api/escalations/${refundId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, note }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function sendChat(payload: {
  customer_email: string;
  message: string;
  history: ChatTurn[];
  session_id: string | null;
}): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<ChatResponse>;
}

export interface StreamHandlers {
  onStart?: (d: { session_id: string; request_id: string; injection_flagged: boolean; injection_tags: string[] }) => void;
  onToken?: (text: string) => void;
  onToolStart?: (d: { name: string; input: Record<string, unknown> }) => void;
  onToolResult?: (d: { name: string; ok: boolean; output: unknown }) => void;
  onDone?: (d: { decision: string; run_id: number; session_id: string; summary: Record<string, number | string> }) => void;
  onError?: (message: string) => void;
}

// POST /api/chat/stream and parse the Server-Sent Events (EventSource is GET-only).
export async function streamChat(
  payload: { customer_email: string; message: string; history: ChatTurn[]; session_id: string | null },
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const b = await res.json();
      if (b?.detail) detail = b.detail;
    } catch {
      /* ignore */
    }
    handlers.onError?.(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let event = "message";
      let dataStr = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
      }
      if (!dataStr) continue;
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(dataStr);
      } catch {
        continue;
      }
      switch (event) {
        case "start":
          handlers.onStart?.(data as never);
          break;
        case "token":
          handlers.onToken?.(String(data.text ?? ""));
          break;
        case "tool_start":
          handlers.onToolStart?.(data as never);
          break;
        case "tool_result":
          handlers.onToolResult?.(data as never);
          break;
        case "done":
          handlers.onDone?.(data as never);
          break;
        case "error":
          handlers.onError?.(String(data.message ?? "stream error"));
          break;
      }
    }
  }
}

export const TOOL_LABELS: Record<string, string> = {
  get_account_summary: "Checking your account…",
  get_orders: "Looking up your orders…",
  get_order_details: "Reviewing the order…",
  get_refund_policy: "Checking the refund policy…",
  check_refund_eligibility: "Checking refund eligibility…",
  submit_refund: "Recording the refund decision…",
  escalate_to_human: "Escalating to a human reviewer…",
};

export function decisionClass(decision: string): string {
  switch (decision) {
    case "approved":
      return "badge badge-approved";
    case "denied":
      return "badge badge-denied";
    case "escalated":
      return "badge badge-escalated";
    default:
      return "badge badge-pending";
  }
}
