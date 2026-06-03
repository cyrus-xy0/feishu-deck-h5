#!/usr/bin/env node
// Upload a file to Magic Builder TOS and print its public URL.
// Adapted from the official magic-builder upload-file-to-tos skill.

const fs = require("fs");
const path = require("path");

const DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn";
const PART_SIZE = 10 * 1024 * 1024;
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

function parseArgs(argv) {
  const opts = { quiet: false, baseUrl: "", key: "", contentType: "", filePath: "" };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--key") opts.key = argv[++i] || "";
    else if (arg === "--content-type") opts.contentType = argv[++i] || "";
    else if (arg === "--base-url" || arg === "--magic-base-url") opts.baseUrl = argv[++i] || "";
    else if (arg === "-q" || arg === "--quiet") opts.quiet = true;
    else if (!arg.startsWith("-") && !opts.filePath) opts.filePath = arg;
  }
  return opts;
}

async function sign(filename, contentType, key, apiBase) {
  const body = { filename, contentType };
  if (key) body.key = key;
  const response = await fetch(`${apiBase}/api/tos/sign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await response.json();
  if (json.code !== 0) throw new Error(`Sign failed: ${json.msg}`);
  return json.data;
}

async function uploadSingle(filePath, filename, contentType, opts, apiBase) {
  const { signed_url, url } = await sign(filename, contentType, opts.key, apiBase);
  const response = await fetch(signed_url, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: fs.readFileSync(filePath),
  });
  if (!response.ok) throw new Error(`PUT failed: HTTP ${response.status} ${await response.text().catch(() => "")}`);
  return url;
}

async function uploadMultipart(filePath, filename, contentType, opts, apiBase) {
  const initResp = await fetch(`${apiBase}/api/tos/multipart/init`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, contentType }),
  });
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
      const partResp = await fetch(`${apiBase}/api/tos/multipart/part`, { method: "POST", body: form });
      const partJson = await partResp.json();
      if (partJson.code !== 0) throw new Error(`Part ${i + 1} failed: ${partJson.msg}`);
      parts.push({ partNumber: i + 1, etag: partJson.data.etag });
    }
  } finally {
    fs.closeSync(fd);
  }
  const completeResp = await fetch(`${apiBase}/api/tos/multipart/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uploadId, key, parts }),
  });
  const completeJson = await completeResp.json();
  if (completeJson.code !== 0) throw new Error(`Complete failed: ${completeJson.msg}`);
  return completeJson.data.url || url;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.filePath) throw new Error("Usage: node assets/magic-upload.js <file> [--key <tos-key>] [--content-type <mime>] [--base-url <url>] [-q]");
  const absPath = path.resolve(opts.filePath);
  if (!fs.existsSync(absPath)) throw new Error(`File not found: ${absPath}`);
  const filename = path.basename(absPath);
  const ext = path.extname(filename).toLowerCase();
  const contentType = opts.contentType || MIME_MAP[ext] || "application/octet-stream";
  const apiBase = normalizeBaseUrl(opts.baseUrl);
  const size = fs.statSync(absPath).size;
  const url = size > 16 * 1024 * 1024
    ? await uploadMultipart(absPath, filename, contentType, opts, apiBase)
    : await uploadSingle(absPath, filename, contentType, opts, apiBase);
  if (opts.quiet) process.stdout.write(url);
  else console.log(`URL: ${url}`);
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
