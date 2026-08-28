from pathlib import Path


def test_deactivation_wrapper_composes_separate_auth_and_core_roles() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts" / "deactivate-researcher").read_text()

    validate = source.index('"$repo_root/scripts/production-runtime" validate')
    clear_ambient = source.index("unset ", validate)
    resolve = source.index("compose_run auth node dist/operator.js resolve")
    inspect = source.index("compose_run api thesistrace-core-access-inspect")
    mutate = source.index("compose_run auth node dist/operator.js deactivate")

    assert validate < clear_ambient < resolve < inspect < mutate
    for variable in (
        "BETTER_AUTH_SECRET",
        "RESEND_API_KEY",
        "RESEND_FROM_EMAIL",
        "THESISTRACE_AUTH_DATABASE_PASSWORD",
        "THESISTRACE_AUTH_IMAGE",
        "THESISTRACE_CORE_DATABASE_PASSWORD",
        "THESISTRACE_ENVIRONMENT",
        "THESISTRACE_OWNER_DATABASE_PASSWORD",
        "THESISTRACE_PUBLIC_ORIGIN",
        "THESISTRACE_RESEND_API_URL",
    ):
        assert variable in source[clear_ambient:resolve]
    assert "active-daily-tracks --researcher-id" in source
    assert "--researcher-id \"$researcher_id\"" in source
    assert "stop" not in source.lower()
    assert "auth." not in source
    assert "daily_tracks." not in source
