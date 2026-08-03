from __future__ import annotations

import json
import os

from thesistrace.tushare_source import HttpTushareTransport, TushareAdapter


def main() -> None:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is required for the live Tushare gate")
    transport = HttpTushareTransport()
    try:
        result = TushareAdapter(token=token, transport=transport).preflight()
    finally:
        transport.close()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
