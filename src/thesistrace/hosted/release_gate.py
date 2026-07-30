import os


class ReleaseGateError(RuntimeError):
    pass


def main() -> None:
    expected = os.environ.get("THESISTRACE_RELEASE_VERSION")
    if not expected:
        raise ReleaseGateError("THESISTRACE_RELEASE_VERSION is required")
    print(f"release gate passed for {expected}")


if __name__ == "__main__":
    main()
