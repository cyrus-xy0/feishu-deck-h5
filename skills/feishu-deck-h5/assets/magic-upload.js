#!/usr/bin/env node
// Upload a file to Magic Builder TOS and print its public URL.
// Adapted from the official magic-builder upload-file-to-tos skill.

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const readline = require("readline");

const DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn";
const PART_SIZE = 10 * 1024 * 1024;
const FETCH_TIMEOUT_MS = Number(process.env.MAGIC_UPLOAD_TIMEOUT_MS || 45000);
const BATCH_PROTOCOL = "magic-upload-batch/v1";
const MAX_BATCH_ITEMS = 10000;
const MAX_BATCH_WORKERS = 16;
const MAX_MANIFEST_BYTES = 10 * 1024 * 1024;
const MIME_MAP = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".bmp": "image/bmp",
  ".html": "text/html",
  ".css": "text/css",
  ".js": "application/javascript",
  ".json": "application/json",
};

function normalizeBaseUrl(value) {
  const raw = String(value || DEFAULT_MAGIC_BASE_URL).trim().replace(/\/+$/, "");
  if (!raw) return DEFAULT_MAGIC_BASE_URL;
  return /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithRetry(url, options, label, retries = 2) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      if (!response.ok && attempt < retries && (response.status === 429 || response.status >= 500)) {
        lastError = new Error(`${label} failed: HTTP ${response.status}`);
      } else {
        return response;
      }
    } catch (error) {
      lastError = error?.name === "AbortError"
        ? new Error(`${label} timed out after ${FETCH_TIMEOUT_MS}ms`)
        : error;
    } finally {
      clearTimeout(timeout);
    }
    if (attempt < retries) await sleep(750 * (attempt + 1));
  }
  throw lastError || new Error(`${label} failed`);
}

function parseArgs(argv) {
  const opts = {
    quiet: false,
    baseUrl: "",
    key: "",
    contentType: "",
    filePath: "",
    batchManifest: "",
    batchNdjson: false,
    workers: 6,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--key") opts.key = argv[++i] || "";
    else if (arg === "--content-type") opts.contentType = argv[++i] || "";
    else if (arg === "--base-url" || arg === "--magic-base-url") opts.baseUrl = argv[++i] || "";
    else if (arg === "--batch-manifest") opts.batchManifest = argv[++i] || "";
    else if (arg === "--batch-ndjson") opts.batchNdjson = true;
    else if (arg === "--workers") opts.workers = Number(argv[++i] || 6);
    else if (arg === "-q" || arg === "--quiet") opts.quiet = true;
    else if (!arg.startsWith("-") && !opts.filePath) opts.filePath = arg;
  }
  return opts;
}

async function sign(filename, contentType, key, apiBase) {
  const body = { filename, contentType };
  if (key) body.key = key;
  const response = await fetchWithRetry(`${apiBase}/api/tos/sign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, "Sign");
  if (!response.ok) throw new Error(`Sign failed: HTTP ${response.status} ${await response.text().catch(() => "")}`);
  const json = await response.json();
  if (json.code !== 0) throw new Error(`Sign failed: ${json.msg}`);
  return json.data;
}

async function uploadSingle(filePath, filename, contentType, opts, apiBase) {
  const { signed_url, url } = await sign(filename, contentType, opts.key, apiBase);
  const response = await fetchWithRetry(signed_url, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: fs.readFileSync(filePath),
  }, "PUT");
  if (!response.ok) throw new Error(`PUT failed: HTTP ${response.status} ${await response.text().catch(() => "")}`);
  return url;
}

async function uploadMultipart(filePath, filename, contentType, opts, apiBase) {
  const initBody = { filename, contentType };
  if (opts.key) initBody.key = opts.key;
  const initResp = await fetchWithRetry(`${apiBase}/api/tos/multipart/init`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(initBody),
  }, "Multipart init");
  if (!initResp.ok) throw new Error(`Init failed: HTTP ${initResp.status} ${await initResp.text().catch(() => "")}`);
  const initJson = await initResp.json();
  if (initJson.code !== 0) throw new Error(`Init failed: ${initJson.msg}`);
  const { uploadId, key, url } = initJson.data;
  const size = fs.statSync(filePath).size;
  const parts = [];
  const fd = fs.openSync(filePath, "r");
  try {
    for (let i = 0; i < Math.ceil(size / PART_SIZE); i++) {
      const len = Math.min(PART_SIZE, size - i * PART_SIZE);
      const buf = Buffer.alloc(len);
      fs.readSync(fd, buf, 0, len, i * PART_SIZE);
      const form = new FormData();
      form.append("file", new Blob([buf], { type: contentType }), filename);
      form.append("uploadId", uploadId);
      form.append("key", key);
      form.append("partNumber", String(i + 1));
      const partResp = await fetchWithRetry(`${apiBase}/api/tos/multipart/part`, { method: "POST", body: form }, `Part ${i + 1}`);
      if (!partResp.ok) throw new Error(`Part ${i + 1} failed: HTTP ${partResp.status} ${await partResp.text().catch(() => "")}`);
      const partJson = await partResp.json();
      if (partJson.code !== 0) throw new Error(`Part ${i + 1} failed: ${partJson.msg}`);
      parts.push({ partNumber: i + 1, etag: partJson.data.etag });
    }
  } finally {
    fs.closeSync(fd);
  }
  const completeResp = await fetchWithRetry(`${apiBase}/api/tos/multipart/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uploadId, key, parts }),
  }, "Multipart complete");
  if (!completeResp.ok) throw new Error(`Complete failed: HTTP ${completeResp.status} ${await completeResp.text().catch(() => "")}`);
  const completeJson = await completeResp.json();
  if (completeJson.code !== 0) throw new Error(`Complete failed: ${completeJson.msg}`);
  return completeJson.data.url || url;
}

function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  const fd = fs.openSync(filePath, "r");
  const buf = Buffer.allocUnsafe(1024 * 1024);
  try {
    while (true) {
      const read = fs.readSync(fd, buf, 0, buf.length, null);
      if (!read) break;
      hash.update(buf.subarray(0, read));
    }
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest("hex");
}

function uploadCacheKey(apiBase, key, sha256) {
  return crypto.createHash("sha256")
    .update(`${apiBase}\0${key}\0${sha256}`)
    .digest("hex");
}

function contentTypeFor(filePath, explicit = "") {
  if (explicit) return explicit;
  const ext = path.extname(filePath).toLowerCase();
  return MIME_MAP[ext] || "application/octet-stream";
}

async function uploadPath(filePath, opts, apiBase) {
  const absPath = path.resolve(filePath);
  if (!fs.existsSync(absPath)) throw new Error(`File not found: ${absPath}`);
  if (!fs.statSync(absPath).isFile()) throw new Error(`Not a file: ${absPath}`);
  const filename = path.basename(absPath);
  const contentType = contentTypeFor(absPath, opts.contentType);
  const size = fs.statSync(absPath).size;
  return size > 16 * 1024 * 1024
    ? await uploadMultipart(absPath, filename, contentType, opts, apiBase)
    : await uploadSingle(absPath, filename, contentType, opts, apiBase);
}

async function mapBounded(items, limit, fn) {
  const results = new Array(items.length);
  let cursor = 0;
  const count = Math.max(1, Math.min(MAX_BATCH_WORKERS, Number(limit) || 1, items.length));
  async function worker() {
    while (true) {
      const idx = cursor++;
      if (idx >= items.length) return;
      results[idx] = await fn(items[idx], idx);
    }
  }
  await Promise.all(Array.from({ length: count }, () => worker()));
  return results;
}

function readBatchManifest(manifestPath, apiBase) {
  const abs = path.resolve(manifestPath);
  if (!fs.existsSync(abs)) throw new Error(`Batch manifest not found: ${abs}`);
  const stat = fs.statSync(abs);
  if (!stat.isFile()) throw new Error(`Batch manifest is not a file: ${abs}`);
  if (stat.size > MAX_MANIFEST_BYTES) throw new Error(`Batch manifest exceeds ${MAX_MANIFEST_BYTES} bytes`);
  const manifest = JSON.parse(fs.readFileSync(abs, "utf8"));
  if (manifest?.protocol !== BATCH_PROTOCOL) throw new Error(`Unsupported batch protocol: ${manifest?.protocol || "missing"}`);
  if (!Array.isArray(manifest.items)) throw new Error("Batch manifest items must be an array");
  if (manifest.items.length > MAX_BATCH_ITEMS) throw new Error(`Batch has ${manifest.items.length} items; max ${MAX_BATCH_ITEMS}`);
  if (normalizeBaseUrl(manifest.base_url) !== apiBase) throw new Error("Batch manifest base_url does not match --base-url");
  return manifest;
}

async function runBatchItems(rawItems, workers, apiBase) {
  return mapBounded(rawItems, workers, async (raw, idx) => {
    const id = String(raw?.id || "");
    const key = String(raw?.key || "");
    const expectedSha = String(raw?.sha256 || "").toLowerCase();
    const expectedCache = String(raw?.cache_key || "").toLowerCase();
    const base = { id, key, sha256: expectedSha, cache_key: expectedCache };
    try {
      if (!id || !key || !raw?.file) throw new Error(`item ${idx} missing id/key/file`);
      if (!/^[a-f0-9]{64}$/.test(expectedSha)) throw new Error(`item ${idx} has invalid sha256`);
      const absPath = path.resolve(String(raw.file));
      if (!fs.existsSync(absPath) || !fs.statSync(absPath).isFile()) throw new Error(`File not found: ${absPath}`);
      const actualSha = sha256File(absPath);
      if (actualSha !== expectedSha) throw new Error(`sha256 mismatch for ${key}`);
      const actualCache = uploadCacheKey(apiBase, key, actualSha);
      if (actualCache !== expectedCache || id !== expectedCache) throw new Error(`cache key mismatch for ${key}`);
      const url = await uploadPath(absPath, {
        key,
        contentType: String(raw.content_type || ""),
      }, apiBase);
      return { ...base, ok: true, url };
    } catch (error) {
      return { ...base, ok: false, error: error?.message || String(error) };
    }
  });
}

function batchPayload(items, apiBase, requestId = "") {
  return {
    protocol: BATCH_PROTOCOL,
    request_id: requestId,
    ok: items.every((item) => item.ok),
    base_url: apiBase,
    items,
  };
}

async function runBatch(opts, apiBase) {
  const manifest = readBatchManifest(opts.batchManifest, apiBase);
  const items = await runBatchItems(manifest.items, opts.workers, apiBase);
  const payload = batchPayload(items, apiBase);
  process.stdout.write(JSON.stringify(payload));
  return payload.ok ? 0 : 1;
}

async function runNdjson(opts, apiBase) {
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of rl) {
    if (!line.trim()) continue;
    let payload;
    let requestId = "";
    try {
      const request = JSON.parse(line);
      requestId = String(request?.request_id || "");
      if (request?.protocol !== BATCH_PROTOCOL) throw new Error("unsupported batch protocol");
      if (!Array.isArray(request.items)) throw new Error("batch request items must be an array");
      if (request.items.length > MAX_BATCH_ITEMS) throw new Error(`batch has ${request.items.length} items; max ${MAX_BATCH_ITEMS}`);
      if (normalizeBaseUrl(request.base_url) !== apiBase) throw new Error("batch request base_url mismatch");
      const items = await runBatchItems(request.items, opts.workers, apiBase);
      payload = batchPayload(items, apiBase, requestId);
    } catch (error) {
      payload = {
        protocol: BATCH_PROTOCOL,
        request_id: requestId,
        ok: false,
        base_url: apiBase,
        items: [],
        error: error?.message || String(error),
      };
    }
    process.stdout.write(JSON.stringify(payload) + "\n");
  }
  return 0;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const apiBase = normalizeBaseUrl(opts.baseUrl);
  if (opts.batchNdjson) return runNdjson(opts, apiBase);
  if (opts.batchManifest) return runBatch(opts, apiBase);
  if (!opts.filePath) throw new Error("Usage: node assets/magic-upload.js <file> [--key <tos-key>] [--content-type <mime>] [--base-url <url>] [-q] OR --batch-manifest <json> [--workers N]");
  const url = await uploadPath(opts.filePath, opts, apiBase);
  if (opts.quiet) process.stdout.write(url);
  else console.log(`URL: ${url}`);
  return 0;
}

main().then((code) => {
  process.exitCode = Number(code) || 0;
}).catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
