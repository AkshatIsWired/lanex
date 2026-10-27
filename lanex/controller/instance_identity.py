# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0.
"""Identity carried by an owner-bound Windows appliance server."""
from __future__ import annotations

import os
import re
from typing import Dict, Optional

_UUID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_HASH = re.compile(r"^[0-9a-fA-F]{64}$")


def current() -> Dict[str, Optional[object]]:
    """Return validated immutable identity, or explicit nulls outside Setup."""
    instance_id = os.environ.get("LANEX_INSTANCE_ID", "")
    source_sha = os.environ.get("LANEX_SOURCE_SHA", "")
    manifest_hash = os.environ.get("LANEX_MANIFEST_HASH", "")
    if not (_UUID.fullmatch(instance_id) and _SHA.fullmatch(source_sha)
            and _HASH.fullmatch(manifest_hash)):
        return {"instanceId": None, "source": {"sha": None, "manifestHash": None}}
    return {
        "instanceId": instance_id.lower(),
        "source": {"sha": source_sha.lower(), "manifestHash": manifest_hash.lower()},
    }
