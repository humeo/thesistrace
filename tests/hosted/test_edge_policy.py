import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "validate-cloudflare-edge"
ALLOWLIST = ROOT / "deploy" / "hosted" / "cloudflare-proxy-ranges.txt"
FIREWALL = ROOT / "deploy" / "hosted" / "cloudflare-origin-firewall.nft"


def validate(
    tmp_path: Path,
    *,
    site_address: str,
    trusted_proxies: str,
    origin_tls: str,
    with_certificate: bool = True,
) -> subprocess.CompletedProcess[str]:
    tls_dir = tmp_path / "origin-tls"
    tls_dir.mkdir(parents=True)
    if with_certificate:
        (tls_dir / "cert.pem").write_text("certificate")
        (tls_dir / "key.pem").write_text("private key")
    return subprocess.run(
        [
            "sh",
            str(VALIDATOR),
            site_address,
            trusted_proxies,
            origin_tls,
            str(tls_dir),
            str(ALLOWLIST),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def approved_ranges() -> list[str]:
    return ALLOWLIST.read_text().splitlines()


def test_public_edge_requires_exact_approved_cloudflare_proxy_set(
    tmp_path: Path,
) -> None:
    approved = " ".join(reversed(approved_ranges()))
    accepted = validate(
        tmp_path,
        site_address="https://research.example.test",
        trusted_proxies=approved,
        origin_tls=(
            "/run/secrets/origin-tls/cert.pem "
            "/run/secrets/origin-tls/key.pem"
        ),
    )
    assert accepted.returncode == 0, accepted.stderr

    rejected = validate(
        tmp_path / "broad",
        site_address="https://research.example.test",
        trusted_proxies=f"{approved} 0.0.0.0/0 ::/0",
        origin_tls=(
            "/run/secrets/origin-tls/cert.pem "
            "/run/secrets/origin-tls/key.pem"
        ),
    )
    assert rejected.returncode == 1
    assert "approved Cloudflare CIDR set" in rejected.stderr


def test_public_edge_requires_https_and_origin_certificate(tmp_path: Path) -> None:
    approved = " ".join(approved_ranges())
    insecure = validate(
        tmp_path / "insecure",
        site_address="http://research.example.test",
        trusted_proxies=approved,
        origin_tls="internal",
    )
    assert insecure.returncode == 1

    missing_certificate = validate(
        tmp_path / "missing",
        site_address="https://research.example.test",
        trusted_proxies=approved,
        origin_tls=(
            "/run/secrets/origin-tls/cert.pem "
            "/run/secrets/origin-tls/key.pem"
        ),
        with_certificate=False,
    )
    assert missing_certificate.returncode == 1
    assert "cert.pem and key.pem" in missing_certificate.stderr


def test_localhost_keeps_explicit_local_only_edge_override(tmp_path: Path) -> None:
    accepted = validate(
        tmp_path,
        site_address="https://localhost",
        trusted_proxies="private_ranges",
        origin_tls="internal",
        with_certificate=False,
    )
    assert accepted.returncode == 0


def test_firewall_and_compose_use_the_canonical_cloudflare_allowlist() -> None:
    approved = set(approved_ranges())
    firewall_ranges = set(
        re.findall(r"[0-9a-fA-F:.]+/\d+", FIREWALL.read_text())
    )
    assert firewall_ranges == approved
