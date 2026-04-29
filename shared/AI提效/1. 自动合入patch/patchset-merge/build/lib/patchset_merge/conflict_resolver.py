"""冲突解决策略 - Patchset 内容优先"""
from enum import Enum
from dataclasses import dataclass, field
from typing import List

class ConflictResolution(Enum):
    PATCHSET_PREFERRED = "patchset_preferred"
    CONTEXT_PREFERRED = "context_preferred"
    MANUAL = "manual"

@dataclass
class ResolutionLogEntry:
    type: str
    our: str
    their: str
    resolved_to: str
    reason: str

class ConflictResolver:
    def __init__(self):
        self.resolution_log: List[ResolutionLogEntry] = field(default_factory=list)

    def resolve_conflict(self, our_content: str, their_content: str,
                        patchset_content: str, context: dict) -> tuple[str, str]:
        """
        解决冲突，优先保留 patchset 内容
        Returns: (resolved_content, reason)
        """
        resolved = patchset_content
        reason = "conflict_resolved: patchset_preferred"

        self.resolution_log.append(ResolutionLogEntry(
            type="conflict",
            our=our_content,
            their=their_content,
            resolved_to="patchset",
            reason=reason
        ))

        return resolved, reason

    def get_resolution_log(self) -> List[ResolutionLogEntry]:
        return self.resolution_log
