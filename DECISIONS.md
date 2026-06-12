# Design decisions & tradeoffs

Short rationale for the choices that matter, and what I'd revisit at scale. Written for the
walkthrough conversation.

## 1. The policy is enforced in code, not in the prompt (defense in depth)
**Decision:** a deterministic engine ([`core/policy.py`](backend/app/core/policy.py)) is the source of
truth. `submit_refund` re-validates against it before any write.
**Why:** the brief stresses that customers will try to talk the agent into breaking the rules. A prompt
alone is probabilistic — it can be jailbroken. Putting enforcement in code makes an unauthorized refund
*impossible by construction*: even a fully compromised model that calls `submit_refund` on a final-sale
item gets a `denied` back. The prompt is layer 1 (UX + steering); the engine is layer 2 (the guarantee).
**Tradeoff:** policy logic is duplicated conceptually between the written policy doc and the engine. I
keep the doc human-readable and the engine the executable truth, and test the engine exhaustively.

## 2. Identity is injected server-side, never taken from the model
**Decision:** the authenticated customer is carried in `RunContext`; tools act as that customer and
ignore any customer/order ownership the user asserts.
**Why:** impersonation ("refund order X" belonging to someone else) becomes structurally impossible, and
another customer's data is never revealed. This is the kind of authz bug LLM apps routinely ship.

## 3. LangGraph + tool calling (over raw loop or CrewAI)
**Decision:** a small `agent ⇄ tools` `StateGraph`.
**Why:** explicit, inspectable state machine; first-class streaming and instrumentation hooks; not as
heavy or opinionated as a multi-agent framework for a single-agent task. The tool layer is the only way
the agent touches the world, which keeps the security boundary small.

## 4. Two layers of observability
**Decision:** an in-app `Tracer` (persisted per run, powers the admin dashboard) **and** LangSmith.
**Why:** the in-app trace is the product surface the brief asks for (reasoning/tool/cost/latency/retries
visible to an operator and replayable); LangSmith is the engineer's deep-debugging view. They serve
different audiences. Cost is computed from a per-model price table so the number is real, not estimated.

## 5. An evaluation harness is the resilience metric
**Decision:** [`evals/`](backend/evals/) runs the agent against a labeled set (happy / edge / escalation /
adversarial) and reports decision accuracy, **policy-violation rate (target 0)**, escalation accuracy,
cost/latency, plus an LLM-as-judge for tone. CI can gate on it (non-zero exit on a violation).
**Why:** "agent resilience" is only credible if it's measured. This turns "it seems to hold the line"
into a number, and makes regressions visible. For adversarial scenarios, success is defined as
*not approving* (a verbal refusal and a recorded denial both count) — the violation metric is the gate.

## 6. Streaming uses an unrolled loop, separate from the graph
**Decision:** the SSE endpoint ([`agent/streaming.py`](backend/app/agent/streaming.py)) runs the same
tools/policy/tracer but unrolls the loop so it can emit token deltas + live tool status; the graph stays
the path for the JSON API, eval, and tests.
**Why:** token-accurate usage accounting is cleanest on the non-streaming `.invoke` path, and the
streaming UX wants fine-grained events. Keeping both avoids compromising either. Same enforcement either
way (`submit_refund` re-validates).

## 7. Edge hardening: idempotency, rate limiting, request IDs, input guardrail
**Decision:** `Idempotency-Key` replay (no double refund on retry), per-IP rate limit, request-id on every
response + structured errors, and a heuristic prompt-injection **detector that flags-and-logs** rather
than blocks.
**Why blocking is observe-only:** the policy engine already makes injection harmless, so a hard block
would mostly add false-positive lockouts; flagging gives the resilience signal (visible in the dashboard
+ stats) without degrading good users. The flag is data, the engine is the defense.

## 8. Human-in-the-loop closes the escalation rule
**Decision:** refunds over $500 are recorded as `escalated` and surfaced in an admin review queue with
approve/deny actions (`decided_by = human`).
**Why:** "requires human escalation" is only complete if a human can actually act on it. This makes the
escalation path a real workflow, not a dead end.

## 9. SQLite + auto-seed; provider-swappable LLM
**Decision:** SQLite via SQLAlchemy with create-all + auto-seed for zero-config startup; the LLM is one
small module.
**Tradeoff:** SQLite is ephemeral on free hosting (fine for a demo; swap to Postgres for persistence —
the ORM doesn't change). The provider swap (Anthropic → OpenAI touched only config/nodes/pricing/deps)
is the proof the orchestration layer is properly isolated.

## What I'd add before production
- Real auth (session/JWT) — today the "signed-in" email is the trusted identity (server-enforced, but a stand-in).
- Postgres + Alembic migrations instead of create-all; idempotency-key TTL/eviction.
- PII redaction in logs/traces; secret management; per-customer (not just per-IP) rate limits backed by Redis.
- Expanded eval set + scheduled eval gate in CI; alerting on policy-violation-rate > 0 and on injection spikes.
- Streaming reconnect/resume and message-queue durability for long sessions.
