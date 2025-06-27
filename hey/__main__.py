"""Main entry point for the hey CLI."""
import argparse
import os
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .api import DuckAI
from .config import Config, load_config
from .memory import get_cache


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
""")
    parser.add_argument('--agree-tos', action='store_true', help='agree to the DuckDuckGo TOS')
    parser.add_argument('--quiet', '-q', action='store_true', help='do not show progress meter')
    parser.add_argument('--verbose', '-v', action='store_true', help='enable verbose logging')
    parser.add_argument('--prompt', '-p', help='set a system prompt for all responses')
    parser.add_argument('--save-prompt', action='store_true', help='save the provided prompt to config')
    parser.add_argument('--proxy', metavar='URL', help='HTTP/HTTPS proxy URL (e.g., http://proxy:8080)')
    parser.add_argument('--socks-proxy', metavar='URL', help='SOCKS proxy URL (e.g., socks5://proxy:1080)')
    parser.add_argument('args', nargs='*', help='chat query or "config" command')
    args = parser.parse_args()

    console = Console()
    console_error = Console(stderr=True)

    config = load_config()
    if not config:
        config = Config()
    config.verbose = args.verbose

    if args.proxy:
        if not config.validate_proxy_url(args.proxy):
            console_error.print(
                f"[bold red]Error:[/] Invalid HTTP proxy URL format: {args.proxy}")
            sys.exit(1)
        config.proxy = args.proxy
        if args.save_prompt:
            config.save()
            console.print(f"[green]HTTP proxy saved[/]")

    if args.socks_proxy:
        if not config.validate_proxy_url(args.socks_proxy, allow_socks=True):
            console_error.print(
                f"[bold red]Error:[/] Invalid SOCKS proxy URL format: {args.socks_proxy}")
            sys.exit(1)
        config.socks_proxy = args.socks_proxy
        if args.save_prompt:
            config.save()
            console.print(f"[green]SOCKS proxy saved[/]")

    proxies = config.get_proxies()
    client = httpx.Client(
        transport=httpx.HTTPTransport(retries=2),
        verify=True,
        follow_redirects=True,
        timeout=30.0,
        proxies=proxies or None
    )

    if os.getenv('HEY_DEBUG'):

        def log_request(request):
            print(request)
            print(request.headers)
            print(request.content)

        def log_response(response):
            print(response)
            print(response.headers)
            print(response.read())

        client.event_hooks = {
            'request': [log_request],
            'response': [log_response],
        }

    if len(args.args) == 1:
        if args.args[0] == "config":
            from .cli import run_config
            run_config(client)
            return
        if args.args[0] == "clear":
            cache = get_cache()
            cache.clear()
            console.print("[green]Message cache cleared[/]")
            return

    if args.agree_tos:
        if not config.tos:
            console.print("[green]Terms of Service accepted[/]")
        config.tos = True
        config.save()

    if args.prompt:
        config.prompt = args.prompt
        if args.save_prompt:
            config.save()
            console.print(f"[green]System prompt saved[/]")

    if not config.tos:
        console_error.print(
            "[bold red]Error:[/] You must agree to DuckDuckGo's Terms of Service to use this tool")
        console_error.print("Read them here: https://duckduckgo.com/terms")
        console_error.print(
            "Once you read it, pass --agree-tos parameter to agree.")
        console_error.print(
            f"[yellow]Note: if you want to, modify `tos` parameter in {Path(Config.get_path()) / Config.get_file_name()}[/]")
        sys.exit(3)

    if not sys.stdout.isatty():
        console_error.print(
            "[bold red]Error:[/] This program must be run in a terminal")
        sys.exit(1)

    query_str = ' '.join(args.args)
    if not query_str:
        console_error.print("[bold red]Error:[/] Please provide a query")
        sys.exit(1)

    api = DuckAI(client, config)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Initializing...[/]"),
            transient=True,  # Remove progress bar when done
            console=console_error,  # Show on stderr to not interfere with response
            disable=args.quiet,
        ) as progress:
            task = progress.add_task("", total=None)  # Indeterminate progress

            progress.update(task, description="[bold blue]Getting verification token...[/]")
            vqd = api.get_vqd()

            progress.update(task, description="[bold blue]Connecting to DuckDuckGo...[/]")
            api.get_response(query_str, vqd)

    except Exception:
        console_error.print_exception()
        sys.exit(1)
    finally:
        client.close()
