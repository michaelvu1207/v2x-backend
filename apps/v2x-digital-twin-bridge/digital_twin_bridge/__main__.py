"""
Entry point for the Digital Twin Camera Bridge service.

Ties together all subsystems: CARLA connection, V2X polling, camera
pool, scheduling, encoding, and upload/persistence.

Run with::

    python -m digital_twin_bridge
"""

import os
import sys
import time
import logging

from digital_twin_bridge.config import Config
from digital_twin_bridge.carla_connection import CarlaConnection
from digital_twin_bridge.object_registry import ObjectRegistry
from digital_twin_bridge.camera_scheduler import CameraScheduler
from digital_twin_bridge.camera_pool import CameraPool
from digital_twin_bridge.v2x_poller import V2XPoller
from digital_twin_bridge.prop_spawner import PropSpawner
from digital_twin_bridge.uplink import Uplink
from digital_twin_bridge.map_data import MapDataExporter
from digital_twin_bridge.health import HealthMonitor

logger = logging.getLogger(__name__)


def main() -> None:
    # ------------------------------------------------------------------ #
    # Configuration & logging                                             #
    # ------------------------------------------------------------------ #
    config = Config.from_env()
    config.setup_logging()

    logger.info("=" * 60)
    logger.info("Digital Twin Camera Bridge starting")
    logger.info("=" * 60)
    logger.info("CARLA endpoint : %s:%d", config.CARLA_HOST, config.CARLA_PORT)
    logger.info("V2X API        : %s", config.V2X_API_URL)
    logger.info("Cameras        : %d @ %dx%d", config.NUM_CAMERAS,
                config.CAM_IMAGE_WIDTH, config.CAM_IMAGE_HEIGHT)
    logger.info("Local snapshots: %s", os.path.abspath(config.LOCAL_SNAPSHOT_DIR))

    # ------------------------------------------------------------------ #
    # CARLA connection (context manager restores settings on exit)        #
    # ------------------------------------------------------------------ #
    with CarlaConnection(config) as conn:
        # -------------------------------------------------------------- #
        # Shared subsystems                                               #
        # -------------------------------------------------------------- #
        registry = ObjectRegistry()
        scheduler = CameraScheduler(registry)
        uplink = Uplink(config)
        health = HealthMonitor()
        pool = CameraPool(conn, config)
        spawner = PropSpawner(conn.world, conn.carla_map)
        poller = V2XPoller(config, registry, conn.carla_map)

        # -------------------------------------------------------------- #
        # Startup                                                         #
        # -------------------------------------------------------------- #
        pool.spawn_cameras()
        poller.start()

        # Export the static map data once for the web front-end
        map_exporter = MapDataExporter(conn)
        map_json_path = os.path.join(config.LOCAL_SNAPSHOT_DIR, "map_data.json")
        try:
            map_data = map_exporter.export_to_json(map_json_path)
            logger.info("Map data written to %s", os.path.abspath(map_json_path))
            # Also upload to S3 for the web frontend
            uplink.upload_map_data(map_data)
        except Exception:
            logger.warning("Failed to export map data.", exc_info=True)

        logger.info("Entering main capture loop.  Press Ctrl+C to stop.")

        try:
            while True:
                cycle_start = time.time()

                # ---- Destroy stale CARLA actors (queued by poller thread) ----
                for actor_id in registry.drain_pending_destroy():
                    actor = conn.world.get_actor(actor_id)
                    if actor is not None:
                        actor.destroy()
                        logger.debug("Destroyed stale actor %d.", actor_id)

                # ---- Spawn/sync CARLA actors for V2X objects ----
                spawner.sync(registry)

                # ---- Schedule next batch ----
                batch = scheduler.next_batch(config.NUM_CAMERAS)
                if not batch:
                    logger.debug(
                        "No objects to capture (registry count: %d). "
                        "Sleeping 1 s ...",
                        registry.count,
                    )
                    time.sleep(1.0)
                    continue

                # ---- Capture ----
                results = pool.capture_batch(batch)

                # ---- Upload to S3 ----
                for obj, jpeg_bytes in results:
                    try:
                        metadata = {
                            "object_type": obj.object_type,
                            "lat": str(obj.lat),
                            "lon": str(obj.lon),
                            "confidence": str(obj.confidence),
                            "street_name": obj.street_name,
                            "timestamp_utc": obj.timestamp_utc,
                        }
                        snapshot_url = uplink.upload_snapshot(
                            obj.object_id, jpeg_bytes, metadata
                        )
                        obj.snapshot_url = snapshot_url
                        obj.snapshot_timestamp = (
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        )
                    except Exception:
                        logger.warning(
                            "S3 upload failed for %s, saving locally.",
                            obj.object_id,
                            exc_info=True,
                        )
                        uplink.save_local(obj.object_id, jpeg_bytes)

                    registry.mark_captured(obj.object_id)

                # ---- Publish state.json ----
                status = health.get_status()
                state_objects = []
                for obj in registry.get_all():
                    state_objects.append({
                        "object_id": obj.object_id,
                        "object_type": obj.object_type,
                        "lat": obj.lat,
                        "lon": obj.lon,
                        "confidence": obj.confidence,
                        "street_name": obj.street_name,
                        "timestamp_utc": obj.timestamp_utc,
                        "snapshot_url": getattr(obj, "snapshot_url", None),
                        "snapshot_timestamp": getattr(
                            obj, "snapshot_timestamp", None
                        ),
                        "last_updated": int(time.time() * 1000),
                    })
                bridge_status = {
                    "status": "connected",
                    "carla_fps": status.get("effective_fps", 0),
                    "objects_tracked": registry.count,
                    "cameras_active": config.NUM_CAMERAS,
                    "last_heartbeat": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                }
                try:
                    uplink.publish_state(state_objects, bridge_status)
                except Exception:
                    logger.warning(
                        "Failed to publish state.json.", exc_info=True
                    )

                # ---- Metrics ----
                cycle_time = time.time() - cycle_start
                health.record_cycle(cycle_time, len(results), len(batch))

                logger.info(
                    "Cycle: %.2fs | Captured: %d/%d | Tracked: %d | "
                    "Avg cycle: %.2fs | Total captures: %d | Uptime: %.0fs",
                    cycle_time,
                    len(results),
                    len(batch),
                    registry.count,
                    status["avg_cycle_time"],
                    status["total_captures"],
                    status["uptime_seconds"],
                )

                # ---- Wait for next capture interval ----
                remaining = config.CAPTURE_INTERVAL - cycle_time
                if remaining > 0:
                    time.sleep(remaining)

        except (KeyboardInterrupt, RuntimeError) as exc:
            if isinstance(exc, RuntimeError):
                logger.info("CARLA connection lost. Shutting down ...")
            else:
                logger.info("KeyboardInterrupt received. Shutting down ...")
        finally:
            poller.stop()
            pool.destroy()
            spawner.destroy_all(registry)
            logger.info("Digital Twin Camera Bridge stopped.")


if __name__ == "__main__":
    main()
