"""Agents package for federal document triage."""

def __getattr__(name):
    """Lazy import agents to avoid circular import issues."""
    if name == "ClassifierAgent":
        from agents.classifier_agent import ClassifierAgent
        return ClassifierAgent
    elif name == "IntakeAgent":
        from agents.intake_agent import IntakeAgent
        return IntakeAgent
    elif name == "RouterAgent":
        from agents.router_agent import RouterAgent
        return RouterAgent
    elif name == "AuditorAgent":
        from agents.auditor_agent import AuditorAgent
        return AuditorAgent
    elif name == "SupervisorAgent":
        from agents.supervisor import SupervisorAgent
        return SupervisorAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ClassifierAgent",
    "IntakeAgent",
    "RouterAgent",
    "AuditorAgent",
    "SupervisorAgent",
]
