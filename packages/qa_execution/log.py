"""Execution log (TASK-037): ``.qa/executions/<id>/execution.log``.

One JSON object per line, written as it happens, so a running execution can
be followed with ``tail -f`` and nothing is lost if it is interrupted. Every
line passes through the execution's redactor when it is written.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from qa_core.redaction import Redactor

LOG_FILENAME = "execution.log"


class ExecutionLog:
    def __init__(self, path: Path, redactor: Redactor, clock: Any) -> None:
        self.path = path
        self._redactor = redactor
        self._clock = clock
        self._file: TextIO | None = path.open("a", encoding="utf-8")

    def event(self, event: str, **fields: Any) -> None:
        """Append one event; never raises (logging must not change an outcome)."""
        if self._file is None:
            return
        timestamp: datetime = self._clock()
        record = {"time": timestamp.isoformat(timespec="milliseconds"), "event": event, **fields}
        try:
            line = json.dumps(self._redactor.redact_data(record), ensure_ascii=False, default=str)
            self._file.write(line + "\n")
            self._file.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        file, self._file = self._file, None
        if file is not None:
            file.close()
