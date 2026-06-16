from dataclasses import dataclass, field
from typing import Sequence

from .permissions import AccountType, normalize_account_type
from rag.shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL, normalize_clearance_level


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    email: str
    account_type: AccountType = "member"
    group_paths: Sequence[str] = field(default_factory=tuple)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    permission_version: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        if not isinstance(self.email, str) or "@" not in self.email:
            raise ValueError("email must be a valid email-like string")
        object.__setattr__(self, "account_type", normalize_account_type(self.account_type))
        object.__setattr__(self, "clearance_level", normalize_clearance_level(self.clearance_level))
        if not isinstance(self.permission_version, int) or self.permission_version < 0:
            raise ValueError("permission_version must be a non-negative integer")
        if isinstance(self.group_paths, (str, bytes)):
            raise TypeError("group_paths must be a sequence of strings")

        paths = tuple(self.group_paths)
        if any(not isinstance(path, str) or not path.strip() for path in paths):
            raise ValueError("group_paths must contain only non-empty strings")
        object.__setattr__(self, "group_paths", paths)
