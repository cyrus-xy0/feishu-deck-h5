#!/usr/bin/env node
// Publish a single HTML file to Magic Builder Space / Miaobi HTML Box.
// Adapted from the official magic-builder publish-magic-page skill.

const fs = require("fs");
const path = require("path");
const os = require("os");

const DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn";
const CONFIG_FILE = ".magic-apps.json";
const TOKEN_FILES = [
  path.join(os.homedir(), ".magic-token"),
  path.join(process.cwd(), ".magic-token"),
  path.join(__dirname, ".magic-token"),
];

function normalizeBaseUrl(value) {
  const raw = String(value || DEFAULT_MAGIC_BASE_URL).trim().replace(/\/+$/, "");
  if (!raw) return DEFAULT_MAGIC_BASE_URL;
  return /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
}

function optionValue(args, index, name) {
  const value = args[index + 1];
  if (!value || value.startsWith("--")) throw new Error(`Missing value for ${name}`);
  return value;
}

function parseArgs(argv) {
  const [commandOrFile, ...rest] = argv;
  const args = commandOrFile === "publish" ? rest : [commandOrFile, ...rest].filter(Boolean);
  const options = { title: "", baseUrl: "", openSource: false, remoteId: "" };
  let filePath = "";
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--title") {
      options.title = optionValue(args, i, arg);
      i++;
    } else if (arg.startsWith("--title=")) {
      options.title = arg.slice("--title=".length);
    } else if (arg === "--base-url" || arg === "--magic-base-url") {
      options.baseUrl = optionValue(args, i, arg);
      i++;
    } else if (arg.startsWith("--base-url=")) {
      options.baseUrl = arg.slice("--base-url=".length);
    } else if (arg.startsWith("--magic-base-url=")) {
      options.baseUrl = arg.slice("--magic-base-url=".length);
    } else if (arg === "--remote-id" || arg === "--app-id") {
      options.remoteId = optionValue(args, i, arg);
      i++;
    } else if (arg.startsWith("--remote-id=")) {
      options.remoteId = arg.slice("--remote-id=".length);
    } else if (arg.startsWith("--app-id=")) {
      options.remoteId = arg.slice("--app-id=".length);
    } else if (arg === "--open-source") {
      options.openSource = true;
    } else if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else if (arg.startsWith("-")) {
      throw new Error(`Unknown option: ${arg}`);
    } else if (!filePath) {
      filePath = arg;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return { filePath, options };
}

function readToken() {
  if (process.env.MAGIC_TOKEN) return process.env.MAGIC_TOKEN.trim();
  for (const file of TOKEN_FILES) {
    if (!fs.existsSync(file)) continue;
    const token = fs.readFileSync(file, "utf8").trim();
    if (token) return token;
  }
  throw new Error("Authentication token not found. Set MAGIC_TOKEN or create ~/.magic-token.");
}

function loadConfig() {
  if (!fs.existsSync(CONFIG_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, "utf8"));
  } catch {
    return {};
  }
}

function saveConfig(config) {
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
}

function generateSecret() {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let value = "";
  for (let i = 0; i < 32; i++) value += alphabet[Math.floor(Math.random() * alphabet.length)];
  return value;
}

async function publish(filePath, options) {
  const absPath = path.resolve(filePath);
  if (!fs.existsSync(absPath)) throw new Error(`File not found: ${absPath}`);
  const html = fs.readFileSync(absPath, "utf8");
  const baseUrl = normalizeBaseUrl(options.baseUrl || process.env.MAGIC_BASE_URL);
  const apiBase = `${baseUrl}/api/html-box`;
  const token = readToken();
  const config = loadConfig();
  const relPath = path.relative(process.cwd(), absPath);
  const remoteInfo = config[relPath] || {};
  const remoteId = options.remoteId || remoteInfo.remoteId || "";
  const title = options.title || path.basename(absPath);
  const payload = {
    html,
    title,
    is_open_source: !!options.openSource,
  };
  let url = apiBase;
  let method = "POST";
  if (remoteId) {
    url = `${apiBase}/${remoteId}`;
    method = "PUT";
    console.log(`Updating existing app (ID: ${remoteId})...`);
  } else {
    payload.hmac_secret = generateSecret();
    console.log("Creating new app...");
  }

  const response = await fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`API Error ${response.status}: Invalid JSON response: ${text}`);
  }
  if (!response.ok) throw new Error(`API Error ${response.status}: ${JSON.stringify(data)}`);
  if (data.code !== 0) throw new Error(`Publish failed: ${data.msg || JSON.stringify(data)}`);

  const result = data.data || {};
  const appId = result.record_id || result.id || remoteId;
  const urls = {
    html_box: result.html_box_url || (remoteInfo.urls && remoteInfo.urls.html_box) || (appId ? `${baseUrl}/html-box/${appId}` : ""),
    dashboard: result.dashboard_url || (remoteInfo.urls && remoteInfo.urls.dashboard) || "",
    panel: result.panel_url || (remoteInfo.urls && remoteInfo.urls.panel) || "",
    tab: result.tab_url || (remoteInfo.urls && remoteInfo.urls.tab) || "",
  };
  config[relPath] = {
    remoteId: appId,
    urls,
    last_published: result.updated_at || new Date().toISOString(),
  };
  saveConfig(config);

  console.log("");
  console.log("=".repeat(40));
  console.log("       PUBLISH SUCCESSFUL!");
  console.log("=".repeat(40));
  console.log(`App ID: ${appId}`);
  console.log("-".repeat(40));
  if (urls.html_box) console.log(`Independent Page: ${urls.html_box}`);
  if (urls.dashboard) console.log(`Dashboard Plugin: ${urls.dashboard}`);
  if (urls.panel) console.log(`Feishu Sidebar:   ${urls.panel}`);
  if (urls.tab) console.log(`Feishu Tab:       ${urls.tab}`);
  console.log("=".repeat(40));
}

async function main() {
  const { filePath, options } = parseArgs(process.argv.slice(2));
  if (options.help || !filePath) {
    console.log("Usage: node assets/magic-page-publish.js publish <file> [--title <title>] [--base-url <url>] [--remote-id <id>] [--open-source]");
    return;
  }
  await publish(filePath, options);
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exit(1);
});
