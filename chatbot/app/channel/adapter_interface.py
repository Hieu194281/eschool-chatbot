"""Channel-agnostic adapter interface. Messenger implements now; a future
`ZaloAdapter(ChannelAdapter)` implements the same ABC → dispatch/graph unchanged.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class InboundMessage(BaseModel):
    channel: str
    user_id: str          # PSID for Messenger (page-scoped)
    text: str
    mid: str              # provider message id (dedupe key)
    timestamp: int = 0


class ChannelAdapter(ABC):
    channel: str

    @abstractmethod
    def verify_signature(self, body: bytes, headers) -> bool: ...

    @abstractmethod
    def parse_inbound(self, payload: dict) -> list[InboundMessage]: ...

    @abstractmethod
    async def send_text(self, user_id: str, text: str) -> None: ...

    @abstractmethod
    async def send_typing(self, user_id: str, on: bool) -> None: ...
