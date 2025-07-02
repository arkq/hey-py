import base64
import hashlib
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from threading import Thread
from typing import Iterable, Optional

import httpx

from .cache import Cache
from .config import Config
from .models import ChatMessage, ChatPayload


logger = logging.getLogger("hey")


@dataclass
class ChatChunk:
    """Chat response chunk structure."""
    action: str
    message: str
    role: Optional[str] = None
    created: Optional[datetime] = None
    model: Optional[str] = None
    status: Optional[int] = None
    id: Optional[str] = None


class DuckAI:

    def __init__(self, client: httpx.Client, cache: Cache, config: Config):
        self.client = client
        self.cache = cache
        self.config = config
        self.vqd_js = None

    def _get_common_headers(self):
        """Get the required headers for API requests."""
        return {
            "Host": "duckduckgo.com",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://duckduckgo.com/",
            "Cookie": "dsc=1;dcm=3",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def _get_vqd_hash(self):
        """Get VQD for new query request."""

        if not self.vqd_js:
            logger.debug("Requesting VQD token")
            headers = self._get_common_headers()
            headers.update({"X-Vqd-Accept": "1"})
            response = self.client.get(
                "https://duckduckgo.com/duckchat/v1/status",
                headers=headers,
                follow_redirects=True,
                timeout=10.0)
            if vqd := response.headers.get("x-vqd-hash-1"):
                self.vqd_js = base64.b64decode(vqd).decode()

        script = [
            "const navigator = new (require('node-navigator').Navigator)();",
            "const DOM = new (require('jsdom').JSDOM)('<html/>');",
            "const window = DOM.window;",
            "const document = window.document;",
            f"console.log(JSON.stringify({self.vqd_js}, null, 0));"]
        logger.debug("Generating VQD hash with script: %s", "".join(script))
        vqd = json.loads(subprocess.check_output(["node", "-e", "".join(script)]))
        for i, data in enumerate(vqd["client_hashes"]):
            vqd["client_hashes"][i] = base64.b64encode(
                hashlib.sha256(data.encode()).digest()).decode()

        logger.debug("VQD hash generated")
        data = json.dumps(vqd, separators=(',', ':'))
        return base64.b64encode(data.encode()).decode()

    def query(self, query: str) -> Iterable[ChatChunk]:
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

        vqd_hash = (
            self.cache.get_vqd_hash()
            or self._get_vqd_hash())

        headers = self._get_common_headers()
        headers.update({
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Origin": "https://duckduckgo.com",
            "X-Vqd-Hash-1": vqd_hash,
        })

        logger.debug("Sending chat request")
        with self.client.stream(
            "POST",
            "https://duckduckgo.com/duckchat/v1/chat",
            headers=headers,
            json=asdict(payload),
            timeout=30.0
        ) as response:

            def precache_vqd_hash():
                """Pre-cache VQD hash in a separate thread."""
                self.cache.set_vqd_hash(self._get_vqd_hash())

            if vqd := response.headers.get("x-vqd-hash-1"):
                self.vqd_js = base64.b64decode(vqd).decode()
                thread = Thread(target=precache_vqd_hash)
                thread.start()

            content = ""
            logger.debug("Starting response stream")
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
                        created=datetime.fromtimestamp(data.get("created")),
                        model=data.get("model"),
                        id=data.get("id")
                    )
                if data.get("action") == "error":
                    yield ChatChunk(
                        action=data["action"],
                        message=data["type"],
                        status=data["status"],
                    )

            logger.debug("Response stream completed")

            if content:
                self.cache.add_message(ChatMessage(
                    role="assistant",
                    content=content.strip(),
                ))
            if vqd:
                thread.join()
