// faas_translate.js — Miaobi (妙笔) FaaS that proxies the Feishu / Lark text-translation API.
//
// Call shape (CORS-enabled; text/plain or application/json POST):
//   POST /api/faas/<id>
//   body: { "texts": ["...", "..."], "source": "zh-CN", "target": "en" }
//   ->    { "ok": true,  "translations": ["...", "..."] }   // same length / order as texts
//   ->    { "ok": false, "translations": [...source unchanged...], "error": "..." }  // graceful fallback
//
// Two uses:
//   1. runtime — a deck (or any page) calls this to translate visible text on the fly;
//   2. batch generation — scripts/make_i18n.py --faas-url <this url> fills the e/j fields
//      of an i18n map (sourceText -> {h,e,j}) before baking it into build.py --i18n.
//
// Deploy with the publish-magic-faas skill (or POST /api/faas) to get a record id;
// the callable URL is then `${MAGIC}/api/faas/<id>`.
//
// *** CREDENTIALS / PERMISSION (read before deploying) ***
//   This handler authenticates to Lark as an internal app. It does NOT ship with any
//   credentials baked in. The DEPLOYER must set two environment variables on the FaaS
//   runtime (or provide them via context.env if the runtime injects env that way):
//       LARK_APP_ID       e.g. cli_xxxxxxxxxxxxxxxx
//       LARK_APP_SECRET   the app secret
//   The Lark app must have the `translation:text` permission granted/published.
//   If either var is missing, the handler does NOT throw — it returns the source text
//   unchanged (ok:false, error:"missing_credentials") so callers degrade gracefully.

module.exports = async function (request, context) {
  const cors = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
  };

  // Credentials come from the FaaS runtime env. Prefer process.env; fall back to
  // context.env if the runtime exposes config that way. NEVER hardcode these.
  const env = (typeof process !== "undefined" && process.env) || (context && context.env) || {};
  const APP_ID = env.LARK_APP_ID;
  const APP_SECRET = env.LARK_APP_SECRET;

  // Map common BCP-47 / locale codes to what the Lark translation API expects.
  // (Lark uses ISO-639-1 plus a couple of script-qualified codes; e.g. Traditional
  //  Chinese is "zh-Hant", Simplified is plain "zh".)
  const LM = { "zh-CN": "zh", "zh-TW": "zh-Hant", "zh-HK": "zh-Hant", "zh-Hant": "zh-Hant", "pt-BR": "pt" };
  const mp = (x) => LM[x] || x;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // Feishu translate is an EXHAUSTIBLE quota: the clean zone is only ~2-3 concurrent; at >=4 it
  // mass-trips 99991400 "request trigger frequency limit". So translate with a SMALL concurrency
  // pool (CONC) + retry each item with exponential backoff (MAX_RETRY). Do NOT Promise.all(allTexts)
  // — that bursts the whole batch at once, gets rate-limited, and bakes a half-Chinese (mixed) map.
  const CONC = 3;
  const MAX_RETRY = 8;

  try {
    const method = (request.method || "GET").toUpperCase();
    if (method === "OPTIONS") return new Response("", { status: 204, headers: cors });

    const inp = JSON.parse((await request.text()) || "{}");
    const texts = Array.isArray(inp.texts) ? inp.texts : [];
    const sl = mp(inp.source || "zh-CN");
    const tl = mp(inp.target || "en");

    // No credentials -> graceful fallback (echo source), never throw.
    if (!APP_ID || !APP_SECRET) {
      return new Response(
        JSON.stringify({ ok: false, error: "missing_credentials", translations: texts }),
        { status: 200, headers: cors }
      );
    }

    // 1) tenant_access_token (internal app)
    const tr = await fetch("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id: APP_ID, app_secret: APP_SECRET }),
    });
    const tj = await tr.json();
    const token = tj.tenant_access_token;
    if (!token) {
      // Auth failed (bad creds / missing permission): echo source, don't throw.
      return new Response(
        JSON.stringify({ ok: false, error: "no_token", translations: texts }),
        { status: 200, headers: cors }
      );
    }

    // 2) translate each text; retry with exponential backoff on rate-limit (99991400) and
    //    transient errors; fall back to the source text only after MAX_RETRY attempts.
    async function one(t) {
      if (!t || !t.trim()) return t;
      for (let a = 0; a < MAX_RETRY; a++) {
        try {
          const r = await fetch("https://open.feishu.cn/open-apis/translation/v1/text/translate", {
            method: "POST",
            headers: { Authorization: "Bearer " + token, "Content-Type": "application/json; charset=utf-8" },
            body: JSON.stringify({ source_language: sl, target_language: tl, text: t }),
          });
          const j = await r.json();
          if (j && j.code === 0 && j.data && j.data.text) return j.data.text; // success
          // code !== 0 (incl. 99991400 rate limit) -> back off and retry
        } catch (e) { /* network blip -> back off and retry */ }
        await sleep(Math.min(8000, 400 * Math.pow(2, a)) + Math.floor(Math.random() * 400));
      }
      return t; // exhausted retries -> graceful fallback to source
    }
    // small concurrency pool (CONC) instead of Promise.all(all) to stay inside the quota
    const translations = new Array(texts.length);
    let _i = 0;
    async function _worker() {
      while (_i < texts.length) { const k = _i++; translations[k] = await one(texts[k]); }
    }
    await Promise.all(Array.from({ length: Math.min(CONC, texts.length || 1) }, _worker));
    return new Response(JSON.stringify({ ok: true, translations }), { status: 200, headers: cors });
  } catch (e) {
    // Top-level guard: never throw out of the handler.
    return new Response(
      JSON.stringify({ ok: false, error: String((e && e.message) || e) }),
      { status: 200, headers: cors }
    );
  }
};
