import json
import os
import ssl
import time
import urllib.error
import urllib.request


def request(origin: str, path: str) -> tuple[int, bytes, str]:
    context = None
    if (
        origin.startswith("https://")
        and os.environ.get("THESISTRACE_SMOKE_INSECURE_TLS") == "1"
    ):
        context = ssl._create_unverified_context()
    with urllib.request.urlopen(
        f"{origin.rstrip('/')}{path}",
        timeout=5,
        context=context,
    ) as response:
        return response.status, response.read(), response.headers.get("content-type", "")


def main() -> None:
    origin = os.environ.get("THESISTRACE_HOSTED_ORIGIN")
    if not origin:
        raise SystemExit("THESISTRACE_HOSTED_ORIGIN is required")

    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            web_status, web_body, web_content_type = request(origin, "/")
            api_status, api_body, api_content_type = request(origin, "/api/v1/health")
            health = json.loads(api_body)
            if (
                web_status == 200
                and b"<title>ThesisTrace" in web_body
                and "text/html" in web_content_type
                and api_status == 200
                and "application/json" in api_content_type
                and health.get("status") == "available"
            ):
                print("hosted public-Origin smoke passed")
                return
            last_error = RuntimeError("public Origin returned an unexpected response")
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(2)
    raise SystemExit(f"hosted public-Origin smoke failed: {last_error}")


if __name__ == "__main__":
    main()
