import hashlib
import json
import os
from pathlib import Path

from thesistrace.hosted.release_operations import (
    ReleaseOperationError,
    canonical_json,
    verify_release_configuration,
    verify_release_image_lock,
)


class ReleaseGateError(RuntimeError):
    pass


def main() -> None:
    expected_version = os.environ.get("THESISTRACE_RELEASE_VERSION")
    if not expected_version:
        raise ReleaseGateError("THESISTRACE_RELEASE_VERSION is required")
    expected_bundle_id = os.environ.get("THESISTRACE_RELEASE_BUNDLE_ID")
    if not expected_bundle_id:
        raise ReleaseGateError("THESISTRACE_RELEASE_BUNDLE_ID is required")
    root = Path(
        os.environ.get(
            "THESISTRACE_RELEASE_BUNDLE_ROOT",
            "/run/thesistrace-release",
        )
    )
    try:
        pointer_ids = {
            str(json.loads(path.read_text())["bundle_id"])
            for path in (root / "current.json", root / "candidate.json")
            if path.is_file()
        }
        if expected_bundle_id not in pointer_ids:
            raise ReleaseGateError("requested immutable release bundle is not staged")
        bundle = json.loads(
            (root / "bundles" / expected_bundle_id / "bundle.json").read_text()
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ReleaseGateError("requested immutable release bundle is unavailable") from error
    if (
        bundle.get("version") != expected_version
        or bundle.get("bundle_id") != expected_bundle_id
    ):
        raise ReleaseGateError("release bundle does not match requested version")
    derived_bundle_id = (
        f'{expected_version}-{str(bundle.get("content_sha256", ""))[:16]}'
    )
    if expected_bundle_id != derived_bundle_id:
        raise ReleaseGateError("release bundle identity is invalid")
    body = {
        key: bundle[key]
        for key in (
            "manifest_version",
            "version",
            "compatibility_epoch",
            "source_sha256",
            "bundle_state",
            "content_sha256",
            "components",
            "image_tag",
            "image_ids",
            "custom_images",
            "configuration_paths",
            "configuration_modes",
        )
    }
    digest = hashlib.sha256(canonical_json(body)).hexdigest()
    if digest != bundle.get("manifest_sha256"):
        raise ReleaseGateError("release bundle checksum is invalid")
    try:
        verify_release_configuration(root, expected_bundle_id)
    except ReleaseOperationError as error:
        raise ReleaseGateError("release configuration snapshot is invalid") from error
    try:
        verify_release_image_lock(root, expected_bundle_id)
    except ReleaseOperationError as error:
        raise ReleaseGateError("release image lock is invalid") from error
    print(f"release gate passed for {expected_bundle_id}")


if __name__ == "__main__":
    main()
