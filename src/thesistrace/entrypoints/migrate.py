from __future__ import annotations

import os

from thesistrace.entrypoints.runtime import migrate_core


def main() -> None:
    database_url = os.environ.get("THESISTRACE_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("missing Core configuration: THESISTRACE_DATABASE_URL")
    migrate_core(database_url)


if __name__ == "__main__":
    main()
