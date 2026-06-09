"""Merge app.yaml with secret env vars for gcloud app deploy."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> None:
    if len(sys.argv) != 4:
        print("Usage: merge_deploy_yaml.py app.yaml secrets.yaml output.yaml", file=sys.stderr)
        sys.exit(1)

    app_path, secrets_path, out_path = map(Path, sys.argv[1:4])
    app_cfg = yaml.safe_load(app_path.read_text(encoding="utf-8")) or {}
    secrets_cfg = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}

    merged_env = dict(app_cfg.get("env_variables") or {})
    merged_env.update(secrets_cfg.get("env_variables") or {})
    app_cfg["env_variables"] = merged_env

    out_path.write_text(yaml.safe_dump(app_cfg, sort_keys=False, default_flow_style=False), encoding="utf-8")
    print(f"Wrote {out_path} ({len(merged_env)} env vars)")


if __name__ == "__main__":
    main()
