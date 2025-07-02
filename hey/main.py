import argparse
import logging
import sys

import httpx
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from .api import DuckAI
from .cache import Cache
from .config import Config, load_config


logger = logging.getLogger("hey")


def main():
    parser = argparse.ArgumentParser(
        description="Hey - DuckDuckGo Chat CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
    hey "What is Python?"
    hey how are you
    hey --prompt "You are a Python expert" "How do I use decorators?"
    hey -v "Tell me about asyncio"
    hey --proxy http://proxy:8080 "What's my IP?"
    hey --socks-proxy socks5://proxy:1080 "What's my IP?"

    # Configure settings
    hey config
    # Clear message history cache
    hey clear
""")
    parser.add_argument('--agree-tos', action='store_true', help='agree to the DuckDuckGo TOS')
    parser.add_argument('--verbose', '-v', action='store_true', help='enable verbose logging')
    parser.add_argument('--prompt', '-p', help='set a system prompt for all responses')
    parser.add_argument('--proxy', metavar='URL',
                        help='HTTP/HTTPS proxy URL (e.g., http://proxy:8080)')
    parser.add_argument('--socks-proxy', metavar='URL',
                        help='SOCKS proxy URL (e.g., socks5://proxy:1080)')
    parser.add_argument('--save', action='store_true',
                        help='save provided proxy and/or prompt to config')
    parser.add_argument('args', nargs='*', help='chat query or "config" command')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    console = Console()

    config = load_config()
    if not config:
        config = Config()

    if args.proxy:
        if not config.validate_proxy_url(args.proxy):
            logger.error("Invalid HTTP proxy URL format: %s", args.proxy)
            return 1
        config.proxy = args.proxy
        if args.save:
            config.save()
            logger.info("HTTP proxy saved")

    if args.socks_proxy:
        if not config.validate_proxy_url(args.socks_proxy, allow_socks=True):
            logger.error("Invalid SOCKS proxy URL format: %s", args.socks_proxy)
            return 1
        config.socks_proxy = args.socks_proxy
        if args.save:
            config.save()
            logger.info("SOCKS proxy saved")

    with Cache() as cache:

        proxies = config.get_proxies()
        client = httpx.Client(
            transport=httpx.HTTPTransport(retries=2),
            verify=True,
            follow_redirects=True,
            timeout=30.0,
            proxies=proxies or None
        )

        if len(args.args) == 1:
            if args.args[0] == "config":
                from .cli import run_config
                run_config(client)
                return
            if args.args[0] == "clear":
                cache.clear()
                console.print("Message history cache cleared.")
                return

        if args.agree_tos:
            if not config.tos:
                logger.info("DuckDuckGo Terms of Service accepted")
            config.tos = True
            config.save()

        if args.prompt:
            config.prompt = args.prompt
            if args.save:
                config.save()
                logger.info("System prompt saved")

        if not config.tos:
            console.print(
                "[bold red]Error:[/] You must agree to DuckDuckGo's Terms of Service to use this tool")
            console.print("Read them here: https://duckduckgo.com/terms")
            console.print("Once you read it, pass --agree-tos parameter to agree.")
            return 3

        if not sys.stdout.isatty():
            logger.error("This program must be run in a terminal")
            return 1

        query = ' '.join(args.args)
        if not query:
            logger.error("No query provided")
            return 2

        api = DuckAI(client, cache, config)

        response = ""
        with Live(Markdown(""), console=console, refresh_per_second=4) as live:
            for chunk in api.query(query):
                if chunk.action == "error":
                    logger.warning("Error in response: %d - %s", chunk.status, chunk.message)
                    continue
                response += chunk.message
                live.update(Markdown(response))
