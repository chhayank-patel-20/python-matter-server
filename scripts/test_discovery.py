"""Test script for Matter discovery command."""

import asyncio
import json
import logging
import sys

import websockets

from matter_server.common.models import APICommand

# Configure logging
logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


async def test_discovery(url: str):
    """Test the discovery command via WebSocket."""
    async with websockets.connect(url) as websocket:
        # 1. Start listening to get the first response (usually server_info)
        initial_msg = await websocket.recv()
        LOGGER.info("Received initial message: %s", initial_msg)

        # 2. Send discovery command
        message_id = "test_discovery_1"
        command = {
            "message_id": message_id,
            "command": APICommand.DISCOVER,
            "args": {},
        }

        LOGGER.info("Sending command: %s", command)
        await websocket.send(json.dumps(command))

        # 3. Wait for result
        while True:
            response = await websocket.recv()
            msg = json.loads(response)

            if msg.get("message_id") == message_id:
                LOGGER.info("Received discovery result: %s", json.dumps(msg, indent=2))
                break

            LOGGER.info("Received other message (event?): %s", msg.get("event") or msg)


if __name__ == "__main__":
    url = "ws://localhost:5580/ws"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    try:
        asyncio.run(test_discovery(url))
    except (
        websockets.exceptions.WebSocketException,
        OSError,
        asyncio.CancelledError,
    ) as e:
        LOGGER.error("Failed to run test: %s", e)
