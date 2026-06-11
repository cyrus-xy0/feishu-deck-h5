"""R-IFRAME-REMOTE · remote-iframe offline/headless dud detector (2026-06-11).

A `<iframe src="http(s)://…">` embedded in a slide makes the page's `load`
event hang forever when offline/headless (screenshot/audit tooling burns its
full timeout per frame — a remote larkoffice docx embed cost 3×30s in the
field) and turns a live demo into a silent white box when the venue has no
network/login.

The rule reads the RAW `src` attribute (getAttribute, not the resolved `.src`)
so file:// resolution can't mask or fake the protocol. These cases pin: an
http(s) src fires (warn); a relative/local src never fires; the
`data-allow-remote-iframe` opt-out (explicit "venue has network+login"
acceptance) silences it.

Fixture URLs deliberately point at 127.0.0.1:9 (discard port → instant
connection-refused) so the test itself never waits on a network timeout.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-IFRAME-REMOTE"

# Remote-looking but fails instantly (connection refused on localhost:9) —
# the raw attribute is all the rule reads, so the prefix is what matters.
REMOTE_HTTP = "http://127.0.0.1:9/live-demo"
REMOTE_HTTPS = "https://127.0.0.1:9/live-demo"


def _slide(inner, *, extra_attrs=""):
    return (
        f'<div class="slide" data-layout="raw" data-screen-label="x" '
        f'data-slide-key="t"{extra_attrs} '
        'style="position:relative;width:1920px;height:1080px">'
        + inner
        + "</div>"
    )


def _run(html, **kw):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html, **kw)


def test_rule_wired():
    assert E.rule_in_engine(RULE)


def test_remote_http_iframe_fires_warn():
    hits = _run(_slide(f'<iframe src="{REMOTE_HTTP}"></iframe>'))
    assert len(hits) == 1, f"remote http iframe not flagged exactly once: {hits}"
    assert hits[0]["severity"] == "warn", f"must be warn: {hits[0]['severity']}"
    assert REMOTE_HTTP in hits[0].get("message", ""), \
        f"finding should carry the offending src: {hits[0]}"


def test_remote_https_iframe_fires():
    hits = _run(_slide(f'<iframe src="{REMOTE_HTTPS}"></iframe>'))
    assert len(hits) == 1, f"remote https iframe not flagged: {hits}"


def test_relative_iframe_is_clean():
    """A relative/local src resolves to file:// at runtime — the rule must read
    the RAW attribute and stay silent."""
    hits = _run(_slide('<iframe src="./demo/index.html"></iframe>'))
    assert hits == [], f"relative iframe src must not fire: {hits}"


def test_allow_remote_iframe_opt_out_silences():
    """data-allow-remote-iframe on the iframe (or an ancestor) = explicit
    acceptance that the venue has network + login."""
    hits = _run(_slide(
        f'<iframe src="{REMOTE_HTTP}" data-allow-remote-iframe></iframe>'))
    assert hits == [], f"opt-out must silence the finding: {hits}"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
