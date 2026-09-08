# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""Hermetic M4 failure-classification and diagnostic-redaction tests."""

from __future__ import annotations

import pytest

from lanex.controller import platform_env


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
