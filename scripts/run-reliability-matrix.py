#!/usr/bin/env python3
"""Run safe local release scenarios and emit a JSON evidence file."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

from tuxindrive.managed_policy import load_managed_policy
from tuxindrive.models import AppConfig, AppSettings
from tuxindrive.recovery_advisor import advice_for_error
from tuxindrive.reliability import run_scenarios
from tuxindrive.search_index import FolderSearchIndex


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist/reliability-report.json"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def legacy_upgrade() -> str:
            config = AppConfig.from_dict({"settings": {"global_bandwidth_limit": "off"}})
            assert config.settings.search_content_indexing is False
            assert AppConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()
            return "legacy configuration migrated and round-tripped"

        def bounded_index() -> str:
            index = FolderSearchIndex(root / "search.sqlite3", max_entries_per_job=100)
            assert index.search("anything") == []
            return "private empty index opened without network access"

        def recovery_guidance() -> str:
            advice = advice_for_error("token expired: authorization failed")
            assert advice.code == "authorization"
            return "authentication failure maps to actionable recovery"

        def policy_default() -> str:
            policy = load_managed_policy(root / "absent.json", require_root=False)
            settings = AppSettings()
            policy.apply(settings)
            assert not policy.active
            return "absent managed policy preserves user defaults"

        report = run_scenarios((
            ("legacy-upgrade", legacy_upgrade),
            ("bounded-index", bounded_index),
            ("recovery-guidance", recovery_guidance),
            ("managed-policy-default", policy_default),
        ))
    report.write(args.output)
    return 0 if report.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
