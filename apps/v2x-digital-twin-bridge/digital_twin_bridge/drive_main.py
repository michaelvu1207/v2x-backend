"""
Entry point for the Drive Server.

Run with:  python -m digital_twin_bridge.drive_main
"""

import asyncio
import json
import logging
import sys

import websockets

from digital_twin_bridge.config import Config
from digital_twin_bridge.drive_server import serve_drive

logger = logging.getLogger(__name__)


def make_api_fetcher(config: Config):
    """Create an API fetcher function that calls /detections/range."""
    import requests

    base_url = config.V2X_API_URL.rsplit("/detections/", 1)[0]

    def fetch(start: str, end: str, limit: int = 500) -> dict:
        url = f"{base_url}/detections/range"
        params = {"start": start, "end": end, "limit": limit}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    return fetch


async def main():
    config = Config.from_env()
    config.setup_logging()

    if "--dry-run" in sys.argv:
        logger.info("Drive server dry-run OK")
        return

    import carla

    logger.info("Connecting to CARLA at %s:%d", config.CARLA_HOST, config.CARLA_PORT)
    client = carla.Client(config.CARLA_HOST, config.CARLA_PORT)
    client.set_timeout(30.0)
    world = client.get_world()
    carla_map = world.get_map()

    # Clean up any leftover actors from previous sessions
    for actor in world.get_actors().filter("vehicle.*"):
        logger.info("Cleaning up leftover vehicle: %s (id=%d)", actor.type_id, actor.id)
        actor.destroy()
    for actor in world.get_actors().filter("sensor.*"):
        logger.info("Cleaning up leftover sensor: %s (id=%d)", actor.type_id, actor.id)
        actor.destroy()

    # Switch to async mode for real-time driving
    settings = world.get_settings()
    original_sync = settings.synchronous_mode
    settings.synchronous_mode = False
    world.apply_settings(settings)
    logger.info("CARLA switched to async mode for driving")

    api_fetcher = make_api_fetcher(config)

    async def handler(websocket):
        await serve_drive(websocket, world, carla_map, api_fetcher)

    async def periodic_actor_audit():
        """Every 60s, check for orphaned actors when no sessions are active."""
        from digital_twin_bridge.drive_server import _active_sessions
        while True:
            await asyncio.sleep(60)
            if _active_sessions:
                continue  # Sessions active, don't interfere
            try:
                vehicles = world.get_actors().filter("vehicle.*")
                sensors = world.get_actors().filter("sensor.*")
                orphaned = len(vehicles) + len(sensors)
                if orphaned > 0:
                    logger.warning(
                        "Actor audit: %d orphaned actors found (vehicles=%d, sensors=%d). Cleaning up.",
                        orphaned, len(vehicles), len(sensors),
                    )
                    for a in sensors:
                        try:
                            a.stop()
                        except Exception:
                            pass
                        try:
                            a.destroy()
                        except Exception:
                            pass
                    for a in vehicles:
                        try:
                            a.destroy()
                        except Exception:
                            pass
            except Exception as e:
                logger.debug("Actor audit error: %s", e)

    port = config.WS_PORT
    logger.info("Starting drive server on ws://0.0.0.0:%d", port)

    try:
        # Start periodic orphan cleanup
        audit_task = asyncio.create_task(periodic_actor_audit())

        async with websockets.serve(
            handler,
            "0.0.0.0",
            port,
            ping_interval=5,     # Send ping every 5s
            ping_timeout=15,     # Close if no pong within 15s
            close_timeout=5,     # Wait max 5s for close handshake
        ):
            logger.info("Drive server ready. Waiting for connections...")
            await asyncio.Future()
    finally:
        settings = world.get_settings()
        settings.synchronous_mode = original_sync
        world.apply_settings(settings)
        logger.info("CARLA settings restored")


if __name__ == "__main__":
    asyncio.run(main())
