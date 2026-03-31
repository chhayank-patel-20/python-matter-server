#!/usr/bin/env python3
"""CLI Client for Python Matter Server."""

import argparse
import asyncio
import contextlib
import logging

import aiohttp
from chip.clusters import Objects as Clusters

from matter_server.client.client import MatterClient
from matter_server.common.errors import MatterError

# Configure logging
logging.basicConfig(level=logging.WARNING)
LOGGER = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:5580/ws"


async def list_nodes(client: MatterClient):
    """List all commissioned nodes."""
    nodes = client.get_nodes()
    if not nodes:
        print("No nodes found.")
        return
    print(f"{'ID':<5} {'Name':<20} {'Available':<10}")
    print("-" * 40)
    for node in nodes:
        print(f"{node.node_id:<5} {node.name or 'Unknown':<20} {node.available:<10}")


async def get_server_info(client: MatterClient):
    """Get server info."""
    print(f"Connected to Matter Server (v{client.server_info.sdk_version})")
    print(f"Fabric ID: {client.server_info.fabric_id}")
    print(f"Compressed Fabric ID: {client.server_info.compressed_fabric_id}")


async def commission(client: MatterClient, code: str):
    """Commission a new device."""
    print(f"Commissioning device with code: {code}...")
    try:
        node_data = await client.commission_with_code(code)
        print(f"Successfully commissioned node ID: {node_data.node_id}")
    except MatterError as e:
        print(f"Commissioning failed: {e}")


async def send_command(
    client: MatterClient, node_id: int, endpoint_id: int, command_name: str
):
    """Send a command to a device."""
    if command_name.lower() == "on":
        cmd = Clusters.OnOff.Commands.On()
    elif command_name.lower() == "off":
        cmd = Clusters.OnOff.Commands.Off()
    elif command_name.lower() == "toggle":
        cmd = Clusters.OnOff.Commands.Toggle()
    else:
        print(f"Unknown command: {command_name}")
        return

    print(f"Sending {command_name} to node {node_id}, endpoint {endpoint_id}...")
    try:
        await client.send_device_command(node_id, endpoint_id, cmd)
        print("Success.")
    except MatterError as e:
        print(f"Command failed: {e}")


def event_callback(event, data):
    """Handle incoming events."""
    print(f"EVENT: {event.name} -> {data}")


async def listen(client: MatterClient):
    """Listen for events."""
    print("Listening for events... (Press Ctrl+C to stop)")
    client.subscribe_events(event_callback)
    stop_event = asyncio.Event()
    await stop_event.wait()


async def discover(client: MatterClient):
    """Discover commissionable nodes via BLE/mDNS."""
    print("Discovering commissionable nodes...")
    try:
        nodes = await client.discover_commissionable_nodes()
        if not nodes:
            print("No commissionable nodes found.")
            return
        for node in nodes:
            print(node)
    except MatterError as e:
        print(f"Discovery failed: {e}")


async def main():
    """Run the CLI client."""
    parser = argparse.ArgumentParser(description="Matter Server CLI Client")
    parser.add_argument("--url", default=DEFAULT_URL, help="Server WebSocket URL")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Nodes command
    subparsers.add_parser("nodes", help="List all nodes")

    # Info command
    subparsers.add_parser("info", help="Get server info")

    # Commission command
    comm_parser = subparsers.add_parser("commission", help="Commission a new device")
    comm_parser.add_argument("code", help="Pairing code or QR code")

    # Control commands
    on_parser = subparsers.add_parser("on", help="Turn device on")
    on_parser.add_argument("node_id", type=int, help="Node ID")
    on_parser.add_argument(
        "endpoint_id", type=int, default=1, nargs="?", help="Endpoint ID"
    )

    off_parser = subparsers.add_parser("off", help="Turn device off")
    off_parser.add_argument("node_id", type=int, help="Node ID")
    off_parser.add_argument(
        "endpoint_id", type=int, default=1, nargs="?", help="Endpoint ID"
    )

    toggle_parser = subparsers.add_parser("toggle", help="Toggle device state")
    toggle_parser.add_argument("node_id", type=int, help="Node ID")
    toggle_parser.add_argument(
        "endpoint_id", type=int, default=1, nargs="?", help="Endpoint ID"
    )

    # Discover command
    subparsers.add_parser("discover", help="Discover commissionable nodes via BLE/mDNS")

    # Listen command
    subparsers.add_parser("listen", help="Listen for real-time events")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    async with aiohttp.ClientSession() as session:
        async with MatterClient(args.url, session) as client:
            # Connect and start listening in background to populate nodes
            listen_task = asyncio.create_task(client.start_listening())

            # Wait for initial data
            await asyncio.sleep(1)

            if args.command == "nodes":
                await list_nodes(client)
            elif args.command == "info":
                await get_server_info(client)
            elif args.command == "commission":
                await commission(client, args.code)
            elif args.command == "discover":
                await discover(client)
            elif args.command in ["on", "off", "toggle"]:
                await send_command(client, args.node_id, args.endpoint_id, args.command)
            elif args.command == "listen":
                await listen(client)

            # Cleanup background task
            listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listen_task


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
