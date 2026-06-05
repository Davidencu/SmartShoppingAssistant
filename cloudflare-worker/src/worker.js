/**
 * SmartShop Proxy Worker
 *
 * Receives a POST { url, headers } from the FastAPI backend and fetches the
 * target URL from Cloudflare's edge network. The outbound IP is a Cloudflare
 * PoP address — not the Railway datacenter range that Amazon/Walmart block.
 *
 * Auth: every request must carry the X-Worker-Secret header matching the
 * WORKER_SECRET env var set via `wrangler secret put WORKER_SECRET`.
 */

export default {
  async fetch(request, env) {

    // ── CORS preflight ────────────────────────────────────────────────────
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST",
          "Access-Control-Allow-Headers": "Content-Type, X-Worker-Secret",
        },
      });
    }

    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }

    // ── Authentication ────────────────────────────────────────────────────
    const secret = request.headers.get("X-Worker-Secret");
    if (!secret || secret !== env.WORKER_SECRET) {
      return json({ error: "Unauthorized" }, 401);
    }

    // ── Parse body ────────────────────────────────────────────────────────
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "Invalid JSON body" }, 400);
    }

    const { url, headers: fwdHeaders = {} } = body;

    if (!url || !url.startsWith("http")) {
      return json({ error: "Valid absolute url required" }, 400);
    }

    // Strip auth header in case it was accidentally included
    const cleanHeaders = Object.fromEntries(
      Object.entries(fwdHeaders).filter(
        ([k]) => k.toLowerCase() !== "x-worker-secret"
      )
    );

    // ── Fetch from target ─────────────────────────────────────────────────
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 25_000);

      const resp = await fetch(url, {
        method: "GET",
        headers: cleanHeaders,
        redirect: "follow",
        signal: controller.signal,
      });

      clearTimeout(timer);

      const html = resp.status === 200 ? await resp.text() : "";

      return json({
        status: resp.status,
        html,
        final_url: resp.url,
      });
    } catch (err) {
      return json({ status: 0, html: "", error: String(err) });
    }
  },
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
