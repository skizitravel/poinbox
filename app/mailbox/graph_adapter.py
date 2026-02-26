"""Microsoft Graph mailbox adapter — stub for future integration."""

from typing import List

from app.mailbox.base import MailboxAdapter
from app.schemas import InboxMessage


class GraphMailboxAdapter(MailboxAdapter):
    """Placeholder adapter for Microsoft Graph / Exchange Online.

    TODO (next phase): implement full OAuth2 client-credentials auth flow using
    GRAPH_TENANT_ID, GRAPH_CLIENT_ID, and GRAPH_CLIENT_SECRET from settings.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        mailbox_user: str,
        folder_name: str = "Inbox",
    ) -> None:
        # TODO: initialise the MSAL confidential client here
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.mailbox_user = mailbox_user
        self.folder_name = folder_name

    def _get_access_token(self) -> str:
        """TODO: obtain an access token via client-credentials grant."""
        raise NotImplementedError(
            "Microsoft Graph auth is not yet implemented. "
            "Set MAILBOX_MODE=mock to use the CSV-based mock adapter."
        )

    def fetch_messages(self) -> List[InboxMessage]:
        """TODO: call the Graph /messages endpoint and map results to InboxMessage."""
        raise NotImplementedError(
            "Microsoft Graph integration is not yet implemented. "
            "Set MAILBOX_MODE=mock to use the CSV-based mock adapter."
        )
