import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .models import ChatMessage


@dataclass
class CachedMessage:
    ts: datetime
    message: ChatMessage

    def to_dict(self):
        return {
            "ts": self.ts.isoformat(),
            "role": self.message.role,
            "content": self.message.content,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            ts=datetime.fromisoformat(data["ts"]),
            message=ChatMessage(role=data["role"], content=data["content"]),
        )


class Cache:

    @staticmethod
    def get_cache_dir() -> Path:
        return Path(os.getenv("HEY_CACHE_PATH", os.path.expanduser("~/.cache/hey")))

    @classmethod
    def get_messages_cache_file(cls) -> Path:
        return cls.get_cache_dir() / "messages.json"

    @classmethod
    def get_vqd_cache_file(cls) -> Path:
        return cls.get_cache_dir() / "vqd.base64"

    def __init__(self, max_size: int = 10, expiry_hours: int = 24):
        """Initialize the message cache.

        Args:
            max_size: Maximum number of messages to store
            expiry_hours: Number of hours after which messages expire
        """
        self._messages: list[CachedMessage] = []
        self._expiry_delta = timedelta(hours=expiry_hours)
        self._max_size = max_size
        self._vqd_hash = None
        self.load()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.save()

    def load(self):
        try:
            with open(self.get_messages_cache_file()) as f:
                for msg in json.load(f):
                    self._messages.append(CachedMessage.from_dict(msg))
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Warning: Failed to load message cache: {e}")
        try:
            with open(self.get_vqd_cache_file()) as f:
                self._vqd_hash = f.read().strip()
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Warning: Failed to load VQD hash: {e}")

    def save(self):
        cache_path = self.get_cache_dir()
        cache_path.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.get_messages_cache_file(), 'w') as f:
                json.dump([msg.to_dict() for msg in self._messages], f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save message cache: {e}")
        try:
            with open(self.get_vqd_cache_file(), 'w') as f:
                f.write(self._vqd_hash or "")
        except Exception as e:
            print(f"Warning: Failed to save VQD hash: {e}")

    def clear(self):
        self._messages.clear()

    def add_message(self, message: ChatMessage):
        self._messages.append(CachedMessage(datetime.now(), message))

    def get_messages(self) -> list[ChatMessage]:
        now = datetime.now()
        return [
            msg.message
            for msg in self._messages[-self._max_size:]
            if now - msg.ts <= self._expiry_delta
        ]

    def get_vqd_hash(self):
        return self._vqd_hash

    def set_vqd_hash(self, vqd_hash: str):
        self._vqd_hash = vqd_hash
