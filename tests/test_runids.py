from __future__ import annotations

import re

from spriterrific.runids import default_run_dir


def test_default_run_dir_is_timestamped() -> None:
    path = default_run_dir("run", ["idle", "s", "image"])
    assert path.parts[0] == "runs"
    assert re.match(r"^\d{8}-\d{6}-run-idle-s-image$", path.name)
