import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import toml


@dataclass
class Config:
    """Configuration data."""

    tos: bool = False
    model: str = "claude-3-haiku-20240307"
    prompt: Optional[str] = None  # System prompt to apply to all responses
    proxy: Optional[str] = None  # HTTP/HTTPS proxy URL
    socks_proxy: Optional[str] = None  # SOCKS proxy URL

    @staticmethod
    def get_config_dir() -> Path:
        return Path(os.getenv("HEY_CONFIG_PATH", os.path.expanduser("~/.config/hey")))

    @classmethod
    def get_config_file(cls) -> Path:
        return cls.get_config_dir() / os.getenv("HEY_CONFIG_FILENAME", "conf.toml")

    def load(self) -> None:
        """Load configuration from file."""
        try:
            data = toml.load(self.get_config_file())
            self.tos = data.get("tos", self.tos)
            self.model = data.get("model", self.model)
            self.prompt = data.get("prompt")  # Will be None if not in file
            self.proxy = data.get("proxy")  # Will be None if not in file
            self.socks_proxy = data.get("socks_proxy")  # Will be None if not in file
        except Exception:
            # If there's any error loading the config, use defaults
            pass

    def save(self) -> None:
        """Save configuration to file."""
        config_path = self.get_config_dir()
        config_path.mkdir(parents=True, exist_ok=True)

        config_data = {
            "tos": self.tos,
            "model": self.model,
        }

        # Only save optional fields if they're set
        if self.prompt is not None:
            config_data["prompt"] = self.prompt
        if self.proxy is not None:
            config_data["proxy"] = self.proxy
        if self.socks_proxy is not None:
            config_data["socks_proxy"] = self.socks_proxy

        try:
            with open(self.get_config_file(), 'w') as f:
                toml.dump(config_data, f)
        except Exception as e:
            print(f"Warning: Failed to save configuration: {e}")

    def get_proxies(self) -> dict[str, str]:
        """Get proxy configuration as a dictionary for httpx."""
        proxies = {}

        # Check environment variables first
        env_http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        env_https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        env_socks_proxy = os.getenv("SOCKS_PROXY") or os.getenv("socks_proxy")

        # Then check config values (they override environment variables)
        if self.proxy:
            proxies["http://"] = self.proxy
            proxies["https://"] = self.proxy
        elif env_http_proxy or env_https_proxy:
            if env_http_proxy:
                proxies["http://"] = env_http_proxy
            if env_https_proxy:
                proxies["https://"] = env_https_proxy

        if self.socks_proxy:
            proxies["all://"] = self.socks_proxy
        elif env_socks_proxy:
            proxies["all://"] = env_socks_proxy

        return proxies

    def validate_proxy_url(self, url: str, allow_socks: bool = False) -> bool:
        """Validate a proxy URL format."""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            if allow_socks:
                return parsed.scheme in ("http", "https", "socks4", "socks5")
            return parsed.scheme in ("http", "https")
        except Exception:
            return False
