from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from live_auth import create_private_compose_login_session


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: provision_image_smoke_auth.py OUTPUT")
    output = Path(sys.argv[1]).resolve()
    session = create_private_compose_login_session(
        "production-image-smoke@example.test"
    )
    descriptor = json.dumps(
        {
            "cookie": session.cookie,
            "researcher_id": session.researcher_id,
        },
        sort_keys=True,
    ).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor_fd = os.open(output, flags, 0o600)
    with os.fdopen(descriptor_fd, "wb") as destination:
        destination.write(descriptor)


if __name__ == "__main__":
    main()
