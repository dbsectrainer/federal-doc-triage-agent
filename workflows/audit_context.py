"""Per-workflow audit scope.

The workflow nodes are module-level functions shared by every workflow
invocation.  A single module-level ``AuditorAgent`` would therefore mix audit
events from concurrently processed documents (and one document's finalization
could clear another document's trail).  A ``ContextVar`` gives each
``SupervisorAgent.process_document`` call its own auditor while keeping the
node functions simple.
"""

from __future__ import annotations

import contextvars

from agents.auditor_agent import AuditorAgent

_DEFAULT_AUDITOR = AuditorAgent()

_CURRENT_AUDITOR: contextvars.ContextVar[AuditorAgent] = contextvars.ContextVar(
    "current_auditor", default=_DEFAULT_AUDITOR
)


def get_auditor() -> AuditorAgent:
    """Return the auditor bound to the current workflow invocation."""
    return _CURRENT_AUDITOR.get()


def open_audit_scope() -> contextvars.Token:
    """Bind a fresh auditor to the current context and return its token."""
    return _CURRENT_AUDITOR.set(AuditorAgent())


def close_audit_scope(token: contextvars.Token) -> None:
    """Restore the auditor that was active before ``open_audit_scope``."""
    _CURRENT_AUDITOR.reset(token)
