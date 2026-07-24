from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"

EntityId = Annotated[str, StringConstraints(min_length=1, pattern=ID_PATTERN)]
MachineId = Annotated[str, StringConstraints(min_length=1, pattern=ID_PATTERN)]
OperationId = Annotated[str, StringConstraints(min_length=1, pattern=ID_PATTERN)]
FlowId = Annotated[str, StringConstraints(min_length=1, pattern=ID_PATTERN)]
SignalId = Annotated[str, StringConstraints(min_length=1, pattern=ID_PATTERN)]
