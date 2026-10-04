"""Start on loopback, optionally also on this machine's current Tailscale IPv4."""

import argparse
import ipaddress
import os
import socket
import subprocess
from contextlib import ExitStack

import uvicorn


def tailscale_ipv4():
    result = subprocess.run(
        ["tailscale", "ip", "-4"], capture_output=True, text=True, check=True, timeout=10
    )
    address = ipaddress.IPv4Address(result.stdout.strip())
    if address not in ipaddress.IPv4Network("100.64.0.0/10"):
        raise ValueError("Tailscale did not return a private tailnet IPv4 address")
    return str(address)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tailscale", action="store_true", help="Also listen on Tailscale IPv4")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    addresses = ["127.0.0.1"]
    if args.tailscale:
        addresses.append(tailscale_ipv4())
    # Set before Uvicorn imports the web application. Do not disable Host validation.
    from app.config import Settings

    configured = Settings.from_env().allowed_hosts.split(",")
    hosts = list(dict.fromkeys([h.strip() for h in configured if h.strip()] + addresses))
    os.environ["LINKO_ALLOWED_HOSTS"] = ",".join(hosts)
    with ExitStack() as stack:
        sockets = []
        for address in addresses:
            listener = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((address, args.port))
            listener.listen(2048)
            listener.setblocking(False)
            sockets.append(listener)
            print(f"Linko listening at http://{address}:{args.port}", flush=True)
        server = uvicorn.Server(
            uvicorn.Config("app.web.main:app", port=args.port, proxy_headers=False)
        )
        server.run(sockets=sockets)


if __name__ == "__main__":
    main()
