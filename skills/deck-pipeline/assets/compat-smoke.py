#!/usr/bin/env python3
from compat import finalize_copy_assets_args, parse_preflight_output, validate_args


def main() -> None:
    ok_output = "PREFLIGHT OK\n  skill root: /tmp/skill\n"
    boot_output = (
        "PREFLIGHT BOOTSTRAPPED\n"
        "  source (RO)    : /opt/skill\n"
        "  workspace (RW) : /tmp/work\n"
    )

    ok = parse_preflight_output(ok_output)
    boot = parse_preflight_output(boot_output)

    assert ok["mode"] == "ok"
    assert ok["workspace_root"] == "/tmp/skill"
    assert boot["mode"] == "bootstrapped"
    assert boot["workspace_root"] == "/tmp/work"
    assert validate_args(strict=True, visual=False) == ["--strict", "--no-visual"]
    assert finalize_copy_assets_args("/tmp/output") == ["/tmp/output", "--shared=copy"]
    print("compat smoke ok")


if __name__ == "__main__":
    main()
