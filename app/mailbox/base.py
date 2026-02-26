"""Abstract base class for mailbox adapters."""

from abc import ABC, abstractmethod
from typing import List

from app.schemas import InboxMessage


class MailboxAdapter(ABC):
    """Interface that all mailbox adapters must implement."""

    @abstractmethod
    def fetch_messages(self) -> List[InboxMessage]:
        """Fetch inbox messages and return them as a list of InboxMessage objects."""
        raise NotImplementedError
