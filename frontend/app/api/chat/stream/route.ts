// Streaming proxy for the SSE chat endpoint.
//
// Next.js `rewrites()` BUFFER proxied responses, which breaks Server-Sent Events
// (the browser gets nothing until the stream ends). A Route Handler returning the
// upstream `ReadableStream` body streams it through unbuffered. This handler takes
// precedence over the catch-all `/api/:path*` rewrite for this exact path.
export const dynamic = "force-dynamic";

const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(req: Request): Promise<Response> {
  const upstream = await fetch(`${BACKEND}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
