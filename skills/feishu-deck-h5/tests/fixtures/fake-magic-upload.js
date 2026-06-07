#!/usr/bin/env node
const path = require("path");

const args = process.argv.slice(2);
const file = args[0] || "asset";
let key = path.basename(file);
for (let i = 1; i < args.length; i += 1) {
  if (args[i] === "--key" && args[i + 1]) {
    key = args[i + 1];
    break;
  }
}
process.stdout.write("https://tos.example.test/" + key.replace(/^\/+/, ""));
