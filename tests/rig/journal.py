"""What a rig run has changed and not yet put back, on disk so the next run can put it back after an abort.

Each section is written before the change it guards and cleared once that change is undone; an empty journal is
deleted. scripts/rig.py keeps it in the git common dir, out of the repo: it holds household entity IDs.
"""

import json
import os
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, path: Path):
        self.path = path
        self.sections: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}

    def __bool__(self) -> bool:
        return bool(self.sections)

    def get(self, section: str, default: Any = None) -> Any:
        return self.sections.get(section, default)

    def update(self, **sections: Any) -> None:
        self.sections |= sections
        self.save()

    def clear(self, *sections: str) -> None:
        for section in sections:
            self.sections.pop(section, None)
        self.save()

    def save(self) -> None:
        """Write the file whole and move it into place, so a process killed mid-write leaves the previous one."""
        if not self.sections:
            self.path.unlink(missing_ok=True)
            return
        temp = self.path.with_name(f"{self.path.name}.tmp")
        temp.write_text(json.dumps(self.sections, indent=2))
        os.replace(temp, self.path)
