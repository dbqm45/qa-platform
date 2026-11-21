"""Small filesystem helpers shared by the platform."""

import os
import tempfile
from pathlib import Path


def write_text_atomically(path: Path, text: str, *, keep_mode: bool = False) -> None:
    """Write to a temporary file next to ``path`` and rename it over ``path``.

    Readers see either the old or the new content, never a partial file.
    With ``keep_mode`` the permissions of an existing ``path`` are preserved.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
        if keep_mode and path.exists():
            tmp.chmod(path.stat().st_mode & 0o777)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
