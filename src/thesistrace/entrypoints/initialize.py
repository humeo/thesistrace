from __future__ import annotations

import os

from thesistrace.entrypoints.schema import initialize_core


def main() -> None:
    database_url = os.environ.get("THESISTRACE_DATABASE_URL")
    if database_url is None:
        raise RuntimeError("THESISTRACE_DATABASE_URL is required")
    initialize_core(database_url)


if __name__ == "__main__":
    main()
