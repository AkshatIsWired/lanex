# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""The SSL context for LanEx's own standard-library HTTPS downloads.

``urllib`` uses Python's default context, which trusts only what the
interpreter's OpenSSL finds. The python.org macOS build ships no CA bundle until
its "Install Certificates" command has run, so every stdlib HTTPS request fails
there with CERTIFICATE_VERIFY_FAILED while pip and httpx (which bring certifi)
work. This context trusts the union of:

* the system default store (keeps a corporate inspection CA working);
* certifi's bundle, when certifi is importable (a pinned dependency);
* macOS's ``/etc/ssl/cert.pem``, when present.

Verification and hostname checks stay on; this only adds trust anchors.
"""

from __future__ import annotations

import os
import ssl
import sys
import threading
from typing import List, Optional

_DARWIN_SYSTEM_BUNDLE = "/etc/ssl/cert.pem"
_lock = threading.Lock()
_cached: Optional[ssl.SSLContext] = None


def _extra_bundles() -> List[str]:
    out: List[str] = []
    try:
        import certifi  # type: ignore

        path = certifi.where()
        if path and os.path.isfile(path):
            out.append(path)
    except Exception:
        pass
    if sys.platform == "darwin" and os.path.isfile(_DARWIN_SYSTEM_BUNDLE):
        out.append(_DARWIN_SYSTEM_BUNDLE)
    return out


def build_context() -> ssl.SSLContext:
    """A fresh verifying client context with the extra trust anchors loaded."""
    ctx = ssl.create_default_context()
    for bundle in _extra_bundles():
        try:
            ctx.load_verify_locations(cafile=bundle)
        except (OSError, ssl.SSLError):
            continue
    # create_default_context already sets these; asserted so no caller can
    # ever receive a non-verifying context from here.
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def https_context() -> ssl.SSLContext:
    """The shared context (built once per process)."""
    global _cached
    with _lock:
        if _cached is None:
            _cached = build_context()
        return _cached


def is_cert_failure(exc: BaseException) -> bool:
    """True when *exc* (or the reason it wraps) is a TLS certificate failure.

    Classified by :func:`platform_env.diagnose_network_failure` so the TLS
    markers live in one place."""
    reason = getattr(exc, "reason", None)
    if isinstance(exc, ssl.SSLCertVerificationError) or isinstance(reason, ssl.SSLCertVerificationError):
        return True
    from . import platform_env

    text = f"{type(exc).__name__}: {exc}"
    if reason is not None:
        text += f" {reason}"
    diag = platform_env.diagnose_network_failure(text, dns_result=True)
    return bool(diag and diag.get("category") == "tls")


def cert_failure_advice() -> str:
    """The plain-words next step after a certificate failure."""
    lines = [
        "Check that this computer's date and time are correct.",
        "If you are behind a company proxy or antivirus that inspects HTTPS, "
        "ask for its root certificate to be installed in the system keychain or "
        "certificate store.",
    ]
    if sys.platform == "darwin":
        minor = f"{sys.version_info[0]}.{sys.version_info[1]}"
        lines.append(
            "If Python came from python.org, run its certificate installer once: "
            f"open \"/Applications/Python {minor}/Install Certificates.command\"")
    lines.append("TLS verification stays on; LanEx will not turn it off.")
    return " ".join(lines)
