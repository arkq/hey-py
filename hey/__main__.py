"""Main entry point for the hey CLI."""
import argparse
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import api
from .config import Config, load_config


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

    if len(args.args) == 1 and args.args[0] == "config":
        from .cli import run_config
        run_config()
        return

    config = load_config()
    if not config:
        config = Config()

    if args.agree_tos:
        if not config.tos:
            print("\033[32mTOS accepted\033[0m")
        config.tos = True
        config.save()

    if args.prompt:
        config.prompt = args.prompt
        if args.save_prompt:
            config.save()
            print("\033[32mSaved system prompt to config\033[0m")

    if args.proxy:
        if not config.validate_proxy_url(args.proxy):
            print(f"\033[31mInvalid HTTP proxy URL format: {args.proxy}\033[0m", file=sys.stderr)
            sys.exit(1)
        config.proxy = args.proxy
        if args.save_prompt:
            config.save()
            print("\033[32mSaved proxy settings to config\033[0m")

    if args.socks_proxy:
        if not config.validate_proxy_url(args.socks_proxy, allow_socks=True):
            print(f"\033[31mInvalid SOCKS proxy URL format: {args.socks_proxy}\033[0m", file=sys.stderr)
            sys.exit(1)
        config.socks_proxy = args.socks_proxy
        if args.save_prompt:
            config.save()
            print("\033[32mSaved proxy settings to config\033[0m")

    config.verbose = args.verbose

    if not config.tos:
        print("\033[31mYou must agree to DuckDuckGo's Terms of Service to use this tool.\033[0m", file=sys.stderr)
        print("Read them here: https://duckduckgo.com/terms", file=sys.stderr)
        print("Once you read it, pass --agree-tos parameter to agree.", file=sys.stderr)
        print(f"\033[33mNote: if you want to, modify `tos` parameter in {Path(Config.get_path()) / Config.get_file_name()}\033[0m",
              file=sys.stderr)
        sys.exit(3)

    if not sys.stdout.isatty():
        print("This program must be run in a terminal", file=sys.stderr)
        sys.exit(1)

    query_str = ' '.join(args.args)
    if not query_str:
        print("Please provide a query", file=sys.stderr)
        sys.exit(1)

    proxies = config.get_proxies()

    client = httpx.Client(
        transport=httpx.HTTPTransport(retries=2),
        verify=True,
        follow_redirects=True,
        timeout=30.0,
        proxies=proxies or None
    )

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Initializing...[/]"),
            transient=True,  # Remove progress bar when done
            console=Console(stderr=True),  # Show on stderr to not interfere with response
            disable=args.quiet,
        ) as progress:
            task = progress.add_task("", total=None)  # Indeterminate progress

            progress.update(task, description="[bold blue]Getting verification token...[/]")
            vqd = api.get_vqd(client, config)

            progress.update(task, description="[bold blue]Connecting to DuckDuckGo...[/]")
            api.get_response(client, query_str, vqd, config)

    except Exception as e:
        print(f"\033[31mError: {str(e)}\033[0m", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == '__main__':
    main()
