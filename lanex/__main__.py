# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Allow ``python -m lanex`` as an alias for the ``librelane-gui`` console script.

(After the upstream ``gui`` → ``librelane.gui`` rename this becomes
``python -m librelane.gui``.)
"""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
