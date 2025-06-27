"""DuckDuckGo Chat API client implementation."""
import json
import logging
from dataclasses import asdict, dataclass
from typing import Iterable, Optional

import httpx

from .cache import MessageCache
from .config import Config
from .models import ChatMessage, ChatPayload


@dataclass
class ChatChunk:
    """Chat response chunk structure."""
    action: str
    message: str
    role: Optional[str] = None
    created: Optional[int] = None
    model: Optional[str] = None
    status: Optional[int] = None
    id: Optional[str] = None


class DuckAI:

    def __init__(self, client: httpx.Client, cache: MessageCache, config: Config):
        self.client = client
        self.cache = cache
        self.config = config

    def _get_common_headers(self):
        """Get the required headers for API requests."""
        return {
            "Host": "duckduckgo.com",
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cookie": "dsc=1;dcm=3",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def get_vqd(self) -> tuple[str, str]:
        """Get the VQD token and VQD hash required for chat requests."""

        logging.debug("Requesting VQD token")
        headers = self._get_common_headers()
        headers.update({
            "Cache-Control": "no-store",
            "x-vqd-accept": "1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        })

        response = self.client.get(
            "https://duckduckgo.com/duckchat/v1/status",
            headers=headers,
            follow_redirects=True,
            timeout=10.0
        )

        vqd = response.headers.get("x-vqd-4")
        if not vqd:
            raise ValueError("No VQD header returned")
        logging.debug("Got VQD token: %s", vqd)
        vqd_hash = response.headers.get("x-vqd-hash-1")
        if not vqd_hash:
            raise ValueError("No VQD hash header returned")
        logging.debug("Got VQD hash: %s", vqd_hash)
        return vqd, vqd_hash

    def get_response(self, query: str, vqd: tuple[str, str]) -> Iterable[ChatChunk]:
        """Get chat response from DuckDuckGo."""

        content = ""
        if self.config.prompt:
            content = self.config.prompt + ": "
        content += query

        message = ChatMessage(role="user", content=content)
        self.cache.add_message(message)

        payload = ChatPayload(
            model=self.config.model,
            # Load chat history from cache
            messages=[ChatMessage(role=msg.role, content=msg.content)
                      for msg in self.cache.get_messages()],
        )

        # get headers and add needed headers
        headers = self._get_common_headers()
        headers.update({
            "Content-Type": "application/json",
            "x-vqd-4": vqd[0],
            "x-vqd-hash-1": "initial",  # vqd[1],
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://duckduckgo.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Origin": "https://duckduckgo.com",
        })

        logging.debug("Sending chat request")
        with self.client.stream(
            "POST",
            "https://duckduckgo.com/duckchat/v1/chat",
            headers=headers,
            json=asdict(payload),
            timeout=30.0
        ) as response:

            new_vqd = response.headers.get("x-vqd-4")
            if new_vqd:
                logging.debug("Got new VQD token: %s", new_vqd)
            else:
                logging.warning("No new VQD token returned")

            content = ""
            logging.debug("Starting response stream")
            for line in response.iter_lines():
                if not line:
                    continue

                try:
                    data = json.loads(line.removeprefix("data: "))
                except json.JSONDecodeError:
                    continue

                if data.get("action") == "success" and data.get("message"):
                    content += data["message"]
                    yield ChatChunk(
                        action=data["action"],
                        message=data["message"],
                        role=data.get("role"),
                        created=data.get("created"),
                        model=data.get("model"),
                        id=data.get("id")
                    )
                if data.get("action") == "error":
                    yield ChatChunk(
                        action=data["action"],
                        message=data["type"],
                        status=data["status"],
                    )

            logging.debug("Response stream completed")

            if message:
                message = ChatMessage(role="assistant", content=content.strip())
                self.cache.add_message(message)
