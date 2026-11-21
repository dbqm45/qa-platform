"""HTTP client settings: ``adapters.httpx`` in ``qa.yaml`` (TASK-045)."""

from typing import Annotated

from pydantic import Field

from qa_schemas.base import Identifier, SchemaModel


class HttpConfig(SchemaModel):
    service: Identifier = "api"
    """Environment service whose URL is the base for relative paths; falls back to
    the environment's ``base_url`` when the service is not defined."""
    verify_tls: bool = True
    follow_redirects: bool = False
    """Off by default, so redirects can be asserted explicitly."""
    max_body_bytes: Annotated[int, Field(ge=0, le=1_000_000)] = 10_000
    """How much of each request/response body is kept as evidence."""
