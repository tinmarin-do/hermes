"""Kill switch — safety mechanism to halt all trading."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KILL_SWITCH_PATH = Path(os.environ.get("HERMES_KILL_SWITCH_PATH", "data/kill_switch.json"))


class KillSwitch:
    def __init__(self) -> None:
        self._path = KILL_SWITCH_PATH

    def activate(self, reason: str = "") -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "active": True,
                    "reason": reason,
                    "activated_at": datetime.now(UTC).isoformat(),
                }
            )
        )

    def deactivate(self) -> None:
        self._path.write_text(
            json.dumps(
                {
                    "active": False,
                    "reason": "",
                    "deactivated_at": datetime.now(UTC).isoformat(),
                }
            )
        )

    def is_alive(self) -> bool:
        if not self._path.exists():
            return True
        try:
            data = json.loads(self._path.read_text())
            return not data.get("active", False)
        except (json.JSONDecodeError, OSError):
            return True

    def status(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"active": False, "reason": "", "activated_at": None}
        try:
            data: dict[str, Any] = json.loads(self._path.read_text())
            return data
        except (json.JSONDecodeError, OSError):
            return {"active": False, "reason": "", "activated_at": None}


kill_switch = KillSwitch()
