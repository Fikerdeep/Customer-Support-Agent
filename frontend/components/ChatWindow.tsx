"use client";

import { useEffect, useRef, useState } from "react";
import { decisionClass } from "@/lib/api";

export interface ChatMsg {
  role: "user" | "assistant" | "error";
  content: string;
  decision?: string;
}

export default function ChatWindow({
  messages,
  loading,
  disabled,
  onSend,
}: {
  messages: ChatMsg[];
  loading: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const submit = () => {
    const t = input.trim();
    if (!t || loading || disabled) return;
    onSend(t);
    setInput("");
  };

  return (
    <div className="card chat-window">
      <div className="messages">
        {messages.length === 0 && (
          <div className="muted">
            Pick a customer, then ask for a refund — or click a scenario on the left.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" && m.decision && (
              <div style={{ marginBottom: 6 }}>
                <span className={decisionClass(m.decision)}>{m.decision}</span>
              </div>
            )}
            {m.content}
          </div>
        ))}
        {loading && <div className="msg assistant spinner">Assist is thinking…</div>}
        <div ref={endRef} />
      </div>
      <div className="composer">
        <textarea
          value={input}
          placeholder={disabled ? "Select a customer first…" : "Type a message…"}
          disabled={disabled}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button onClick={submit} disabled={loading || disabled}>
          Send
        </button>
      </div>
    </div>
  );
}
