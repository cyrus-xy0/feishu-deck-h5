// faas_store.js — Miaobi (妙笔) FaaS that gives the editable deck SHARED, cross-device
// persistence. The deck runs inside a sandboxed iframe (no allow-same-origin) where
// localStorage is BLOCKED, so client-side storage can't persist on the published link.
// This FaaS bridges the browser and TOS object storage:
//   GET  /api/faas/<id>          -> { ok:true, data:{edits,order,hidden} }  (reads the TOS blob)
//   POST /api/faas/<id>  (body = JSON state, Content-Type text/plain)        (writes the TOS blob)
// The browser ↔ FaaS hop is CORS-enabled here (ACAO:*) and uses a text/plain POST so it is a
// "simple request" (no preflight). The FaaS ↔ TOS hop is server-side (no CORS needed); TOS itself
// returns no CORS headers, which is exactly why the browser cannot talk to it directly.
//
// Deploy with the publish-magic-faas skill (or POST /api/faas). Each deck should use its OWN KEY
// (one TOS object per deck) — change KEY below before publishing a second deck, or template it.
//
// After publishing you get a record id -> the deck URL is `${MAGIC}/api/faas/<id>`. Pass that to
// build.py via `--faas` (or make_manifest --faas). See references/backend-persistence.md.

module.exports = async function (request, context) {
  const MAGIC = "https://magic.solutionsuite.cn";          // your Magic domain
  const KEY = "deck-store/" + (context && context.id ? context.id : "default") + ".json"; // per-deck object
  const PUBLIC = "https://magic-builder.tos-cn-beijing.volces.com/" + KEY;
  const cors = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
  };
  try {
    const method = (request.method || "GET").toUpperCase();
    if (method === "OPTIONS") return new Response("", { status: 204, headers: cors });

    if (method === "GET") {
      let data = {};
      try {
        const r = await fetch(PUBLIC + "?cb=" + Date.now());
        if (r.ok) { const t = await r.text(); data = JSON.parse(t || "{}"); }
      } catch (e) {}
      return new Response(JSON.stringify({ ok: true, data }), { status: 200, headers: cors });
    }

    // POST: body text is the full deck state JSON; persist to TOS via a signed PUT
    const body = await request.text();
    JSON.parse(body); // validate (throws -> caught below)
    const sg = await fetch(MAGIC + "/api/tos/sign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: KEY.split("/").pop(), contentType: "application/json", key: KEY }),
    });
    const sj = await sg.json();
    if (sj.code !== 0) return new Response(JSON.stringify({ ok: false, error: "sign:" + sj.msg }), { status: 200, headers: cors });
    const put = await fetch(sj.data.signed_url, { method: "PUT", headers: { "Content-Type": "application/json" }, body });
    return new Response(JSON.stringify({ ok: put.ok, status: put.status }), { status: 200, headers: cors });
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: String((e && e.message) || e) }), { status: 200, headers: cors });
  }
};
