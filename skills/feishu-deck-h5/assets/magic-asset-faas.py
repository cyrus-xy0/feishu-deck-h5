#!/usr/bin/env python3
"""Rewrite Magic TOS asset URLs through a binary-safe Magic FaaS proxy.

Magic's TOS upload endpoint can return otherwise valid images/fonts/media with
``Content-Disposition: attachment``. Browsers then leave embedded ``img`` and
CSS ``url()`` slots blank even though the requests return HTTP 200. This helper
publishes a closed FaaS map of the exact TOS URLs already present in one HTML
artifact and rewrites only those URLs through that proxy. It is intentionally
not a general-purpose URL proxy.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import mimetypes
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn"
MAGIC_TOS_URL_RE = re.compile(
    r"https://magic-builder\.tos-cn-beijing\.volces\.com/[^\s\"'<>)}]+",
    re.I,
)
IFRAME_FAAS = Path(__file__).resolve().with_name("magic-iframe-faas.py")


def normalize_base_url(value: str) -> str:
    raw = (value or DEFAULT_MAGIC_BASE_URL).strip().rstrip("/")
    if not raw:
        return DEFAULT_MAGIC_BASE_URL
    return raw if re.match(r"^https?://", raw, re.I) else "https://" + raw


def _load_iframe_faas():
    spec = importlib.util.spec_from_file_location("magic_iframe_faas_shared", IFRAME_FAAS)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load shared FaaS publisher: {IFRAME_FAAS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def asset_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def content_type_for(url: str) -> str:
    path = urlparse(url).path
    guessed, _encoding = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def collect_assets(html: str) -> Dict[str, Dict[str, str]]:
    assets: Dict[str, Dict[str, str]] = {}
    for url in MAGIC_TOS_URL_RE.findall(html):
        key = asset_key(url)
        assets.setdefault(key, {"url": url, "type": content_type_for(url)})
    return assets


def restore_upstream_urls(html: str, report_path: Path) -> str:
    """Reverse a prior proxy rewrite so an artifact can be re-sharded safely."""
    if not report_path.exists():
        return html
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    for row in payload.get("assets") or []:
        key = str(row.get("key") or "")
        url = str(row.get("url") or "")
        if not key or not url:
            continue
        proxy_re = re.compile(
            r"https://magic\.solutionsuite\.cn/api/faas/[^\s\"'<>)}?]+\?a="
            + re.escape(key)
        )
        html = proxy_re.sub(url, html)
    return html


def make_faas_code(assets: Dict[str, Dict[str, str]]) -> str:
    return (
        "const ASSETS = "
        + json.dumps(assets, ensure_ascii=False, indent=2)
        + r''';

module.exports = async function (request, context) {
  try {
    const requestUrl = new URL(request.url);
    const key = requestUrl.searchParams.get("a") || "";
    const asset = ASSETS[key];
    if (!asset) {
      return new Response("Not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    const response = await fetch(asset.url);
    if (!response.ok) {
      return new Response("Upstream error: " + response.status, {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    const body = await response.arrayBuffer();
    const contentType = asset.type || response.headers.get("content-type") || "application/octet-stream";
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=86400, immutable",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch (error) {
    return new Response(String(error && error.message || error), {
      status: 500,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
};
'''
    )


def split_assets(assets: Dict[str, Dict[str, str]], count: int) -> List[Dict[str, Dict[str, str]]]:
    shard_count = max(1, min(int(count or 1), len(assets)))
    shards: List[Dict[str, Dict[str, str]]] = [dict() for _ in range(shard_count)]
    for index, (key, row) in enumerate(assets.items()):
        shards[index % shard_count][key] = row
    return shards


def rewrite_html(
    html: str,
    assets: Dict[str, Dict[str, str]],
    faas_urls: Dict[str, str],
) -> str:
    url_to_proxy = {
        row["url"]: f"{faas_urls[key]}?a={key}" for key, row in assets.items()
    }
    return MAGIC_TOS_URL_RE.sub(lambda match: url_to_proxy[match.group(0)], html)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html")
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--source-report",
        default="",
        help="prior proxy report used to reverse an existing rewrite before re-sharding",
    )
    parser.add_argument("--base-url", default=DEFAULT_MAGIC_BASE_URL)
    parser.add_argument("--faas-name", default="feishu_deck_asset_proxy")
    parser.add_argument("--faas-record-id", default="")
    parser.add_argument(
        "--shards",
        type=int,
        default=8,
        help="number of closed FaaS maps used in parallel (default 8)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv or sys.argv[1:])

    src = Path(args.html).resolve()
    dst = Path(args.out).resolve()
    report_path = Path(args.report).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    html = src.read_text(encoding="utf-8", errors="replace")
    if args.source_report:
        html = restore_upstream_urls(html, Path(args.source_report).resolve())
    assets = collect_assets(html)
    if not assets:
        dst.write_text(html, encoding="utf-8")
        report = {
            "ok": True,
            "rewritten": 0,
            "assets": [],
            "reason": "no Magic TOS asset URLs",
            "output": str(dst),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    base_url = normalize_base_url(args.base_url)
    shared = _load_iframe_faas()
    prior_ids = [part.strip() for part in str(args.faas_record_id or "").split(",") if part.strip()]
    prior_report: Dict[str, Any] = {}
    if report_path.is_file():
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prior_report = loaded
        except (OSError, json.JSONDecodeError, TypeError):
            prior_report = {}
    prior_states = prior_report.get("shard_states") or []
    shards = split_assets(assets, args.shards)
    faas_by_index: Dict[int, Dict[str, Any]] = {}
    metadata_by_index: Dict[int, Dict[str, Any]] = {}
    faas_urls: Dict[str, str] = {}
    reused_shards = 0
    publish_jobs: List[Dict[str, Any]] = []
    for index, shard in enumerate(shards, 1):
        code = make_faas_code(shard)
        code_sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest()
        prior_state = prior_states[index - 1] if index <= len(prior_states) else {}
        prior_faas = prior_state.get("faas") if isinstance(prior_state, dict) else None
        can_reuse = bool(
            isinstance(prior_faas, dict)
            and prior_state.get("code_sha256") == code_sha256
            and bool(prior_faas.get("dry_run")) == bool(args.dry_run)
            and str(prior_faas.get("faas_url") or "").startswith(base_url + "/api/faas/")
        )
        if can_reuse:
            faas = dict(prior_faas)
            faas["reused"] = True
            reused_shards += 1
            faas_by_index[index] = faas
        else:
            publish_jobs.append({
                "index": index,
                "code": code,
                "name": f"{args.faas_name}_{index:02d}",
                "record_id": prior_ids[index - 1] if index <= len(prior_ids) else "",
            })
        metadata_by_index[index] = {
            "index": index,
            "code_sha256": code_sha256,
            "asset_keys": list(shard),
        }

    # Independent closed maps are safe to create/update concurrently. Keeping
    # this bounded turns eight 30-60s API calls from a serial 4-8 minute stage
    # into roughly one or two network rounds.
    if publish_jobs:
        with ThreadPoolExecutor(max_workers=min(4, len(publish_jobs))) as pool:
            future_to_job = {
                pool.submit(
                    shared.publish_faas_api,
                    code=job["code"],
                    name=job["name"],
                    record_id=job["record_id"],
                    base_url=base_url,
                    dry_run=args.dry_run,
                ): job
                for job in publish_jobs
            }
            for future in as_completed(future_to_job):
                job = future_to_job[future]
                faas = future.result()
                faas["reused"] = False
                faas_by_index[job["index"]] = faas

    faas_shards: List[Dict[str, Any]] = []
    shard_states: List[Dict[str, Any]] = []
    for index, shard in enumerate(shards, 1):
        faas = faas_by_index[index]
        faas_shards.append(faas)
        shard_states.append({
            **metadata_by_index[index],
            "faas": faas,
        })
        for key in shard:
            faas_urls[key] = str(faas["faas_url"])
    rewritten = rewrite_html(html, assets, faas_urls)
    dst.write_text(rewritten, encoding="utf-8")
    report: Dict[str, Any] = {
        "ok": True,
        "rewritten": len(assets),
        "faas": faas_shards[0],
        "faas_shards": faas_shards,
        "shard_states": shard_states,
        "reused_shards": reused_shards,
        "published_shards": len(publish_jobs),
        "assets": [
            {"key": key, "url": row["url"], "content_type": row["type"]}
            for key, row in assets.items()
        ],
        "output": str(dst),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
