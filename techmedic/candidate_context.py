"""Explicit, request-scoped flag for pre-release policy. Legacy regression code
still tests unmodified v1.5.5 semantics. Never toggle process-wide globals."""
from contextvars import ContextVar
candidate_active: ContextVar[bool] = ContextVar('pass15_candidate_active', default=False)
