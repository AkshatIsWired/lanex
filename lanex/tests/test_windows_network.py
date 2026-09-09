# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""Hermetic M4 failure-classification and diagnostic-redaction tests."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from lanex.controller import platform_env


REPO = Path(__file__).resolve().parents[2]


def _bash() -> str:
    for candidate in (r"C:\Program Files\Git\bin\bash.exe", "bash"):
        try:
            if subprocess.run([candidate, "--version"], capture_output=True).returncode == 0:
                return candidate
        except OSError:
            pass
    pytest.skip("bash is unavailable")


def _provision_fixture(tmp_path: Path, curl_body: str) -> subprocess.CompletedProcess[str]:
    source = (REPO / "windows" / "provision" / "provision.sh").read_text()
    source = source.rsplit('\nmain "$@"', 1)[0]
    fixture = tmp_path / "provision-functions.sh"
    fixture.write_text(source, encoding="utf-8", newline="\n")
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    curl = mock_bin / "curl"
    curl.write_text("#!/usr/bin/env bash\n" + curl_body, encoding="utf-8", newline="\n")
    curl.chmod(0o755)
    bash = _bash()
    def to_posix(path: Path) -> str:
        value = path.resolve().as_posix()
        if len(value) > 2 and value[1:3] == ":/":
            return "/" + value[0].lower() + value[2:]
        return value
    env = dict(os.environ)
    return subprocess.run(
        [bash, "-c", 'PATH="$2:$PATH"; export PATH; source "$1"; probe_endpoint fixture https://example.invalid/x',
         "bash", to_posix(fixture), to_posix(mock_bin)],
        capture_output=True, text=True, env=env, timeout=15,
    )


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("curl: (6) Could not resolve host: ghcr.io", "dns"),
        ("connect: ENETUNREACH (Network is unreachable)", "route"),
        ("SSL certificate problem: unable to get local issuer certificate", "tls"),
        ("HTTP/1.1 407 Proxy Authentication Required", "proxy-auth"),
        ("HTTP/2 429 Too Many Requests", "rate-limit"),
        ("httpx.ReadTimeout: read timed out", "timeout"),
        ("HTTP/1.1 401 Unauthorized", "http-auth"),
        ("HTTP/1.1 503 Service Unavailable", "http-status"),
        ("Could not get lock /var/lib/dpkg/lock-frontend", "apt-lock"),
        ("dpkg was interrupted, you must manually run 'dpkg --configure -a'", "apt-interrupted"),
        ("E: Unable to locate package klayout", "apt-index"),
        ("[Errno 13] Permission denied: '/owned/pdks'", "permission"),
        ("OSError: [Errno 28] No space left on device", "no-space"),
    ],
)
def test_failure_categories(message: str, category: str) -> None:
    result = platform_env.diagnose_network_failure(message, dns_result=True)
    assert result is not None
    assert result["category"] == category


def test_enetunreach_with_working_dns_is_never_reported_as_dns() -> None:
    result = platform_env.diagnose_network_failure(
        "github.com resolved to 140.82.121.4; connect failed: ENETUNREACH",
        dns_result=True,
    )
    assert result is not None
    assert result["category"] == "route"
    assert result["dns_ok"] is True
    assert "DNS works" in result["summary"]


def test_specific_local_failure_outranks_incidental_timeout() -> None:
    result = platform_env.diagnose_network_failure(
        "download timed out while writing: No space left on device",
        dns_result=True,
    )
    assert result is not None
    assert result["category"] == "no-space"
    assert result["retryable"] is False


def test_diagnostic_tail_is_bounded_and_redacts_credentials() -> None:
    secret = "correct-horse-battery-staple"
    message = "\n".join(["old noise"] * 30 + [
        f"HTTPS_PROXY=https://alice:{secret}@proxy.example:8443",
        f"Proxy-Authorization: Basic {secret}",
        f"GET https://example.test/file?token={secret}&part=1",
        "HTTP/1.1 407 Proxy Authentication Required",
    ])
    result = platform_env.diagnose_network_failure(message, dns_result=True)
    assert result is not None
    assert result["category"] == "proxy-auth"
    assert secret not in result["log_tail"]
    assert "[redacted]" in result["log_tail"]
    assert len(result["log_tail"].splitlines()) <= 20


def test_pac_is_explained_as_unsupported_not_logged_as_a_proxy_url() -> None:
    result = platform_env.diagnose_network_failure(
        "HTTP 407 Proxy Authentication Required; Windows uses a PAC file",
        dns_result=True,
    )
    assert result is not None
    assert "PAC files are not shell proxy URLs" in result["remediation"]


def test_unknown_output_with_working_dns_has_no_false_network_diagnosis() -> None:
    assert platform_env.diagnose_network_failure(
        "compiler returned exit status 1", dns_result=True
    ) is None


def test_provisioning_preserves_dns_and_uses_scoped_ip_fallbacks() -> None:
    script = (REPO / "windows" / "provision" / "provision.sh").read_text()
    assert "nameserver 8\\.8\\.8\\.8" in script  # legacy ownership detection only
    assert "printf 'nameserver 8.8.8.8" not in script
    assert "Acquire::ForceIPv4=true" in script
    assert "Acquire::ForceIPv6=true" in script
    assert "backed up and retired LanEx's legacy public-DNS override" in script
    assert "preserved the existing WSL network section" in script
    assert "mv -f \"$wsl_temp\" /etc/wsl.conf" in script
    assert "the backed-up configuration was restored" in script


def test_provisioning_checks_real_endpoints_and_protocol_statuses() -> None:
    script = (REPO / "windows" / "provision" / "provision.sh").read_text()
    for endpoint in (
        "archive.ubuntu.com", "download.docker.com", "pypi.org/simple/",
        "ghcr.io/v2/", "ciel/releases/latest",
    ):
        assert endpoint in script
    assert "2??|3??|401|405" in script
    assert "407" in script and "429" in script


def test_probe_uses_ipv4_only_for_evidenced_family_mismatch(tmp_path: Path) -> None:
    result = _provision_fixture(tmp_path, r'''
case " $* " in
  *" -4 "*) printf '401'; exit 0 ;;
  *) printf '000'; echo 'curl: (7) Network is unreachable' >&2; exit 7 ;;
esac
''')
    assert result.returncode == 0, result.stderr
    assert "per-command IPv4 fallback" in result.stdout


def test_probe_keeps_working_dns_route_failure_out_of_dns_bucket(tmp_path: Path) -> None:
    result = _provision_fixture(tmp_path, r'''
printf '000'
echo 'curl: (7) Network is unreachable' >&2
exit 7
''')
    assert result.returncode != 0
    assert "route/connection failure" in result.stderr
    assert "DNS failure" not in result.stderr


def test_apt_recovery_is_bounded_and_never_deletes_locks() -> None:
    provision = (REPO / "windows" / "provision" / "provision.sh").read_text()
    install = (REPO / "scripts" / "install.sh").read_text()
    assert "timeout 300 dpkg --configure -a" in provision
    assert "fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock" in provision
    assert "rm -f /var/lib/dpkg/lock" not in provision
    for text in (provision, install):
        assert "Acquire::http::Timeout=30" in text
        assert "Acquire::https::Timeout=30" in text
        assert "Acquire::Retries=3" in text


def test_setup_forwards_proxy_without_logging_values_and_detects_pac() -> None:
    setup = (REPO / "windows" / "installer" / "lanex.iss").read_text()
    assert "HTTP_PROXY:HTTPS_PROXY:NO_PROXY:http_proxy:https_proxy:no_proxy" in setup
    assert "SetProcessEnvironmentVariable('WSLENV', ForwardedWslEnv)" in setup
    assert "SetProcessEnvironmentVariable('WSLENV', PreviousWslEnv)" in setup
    assert "AutoConfigURL" in setup and "PAC address and proxy credentials are not logged" in setup


def test_in_app_apt_strategy_has_bounded_network_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    from lanex.controller import installer

    monkeypatch.setattr(installer, "_check_cmd", lambda name: name == "apt-get")
    argv = installer._strategy_apt({"apt": True}, "gtkwave")
    assert argv is not None
    joined = " ".join(argv)
    assert "DPkg::Lock::Timeout=300" in joined
    assert "Acquire::http::Timeout=30" in joined
    assert "Acquire::https::Timeout=30" in joined
    assert "Acquire::Retries=3" in joined
