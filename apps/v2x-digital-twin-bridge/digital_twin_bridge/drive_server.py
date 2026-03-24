"""
Drive Server — WebSocket server for real-time vehicle control.

Manages driving sessions: scene reconstruction, vehicle spawning,
steering input, camera switching, telemetry + MJPEG frame streaming.
"""

import asyncio
import io
import json
import logging
import math
import time
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np
from PIL import Image

from digital_twin_bridge.scene_reconstructor import SceneReconstructor
from digital_twin_bridge.camera_streamer import compute_camera_transform

logger = logging.getLogger(__name__)

VALID_CAMERA_VIEWS = {"chase", "hood", "bird", "free"}


class DriveSession:
    """
    Manages a single driving session.
    Lifecycle: start() -> apply_control() (repeated) -> end()
    """

    def __init__(self, world, carla_map, api_fetcher: Callable):
        self._world = world
        self._map = carla_map
        self._api_fetcher = api_fetcher
        self._reconstructor: Optional[SceneReconstructor] = None
        self.vehicle = None
        self.active_camera: str = "chase"
        self._active = False
        self._camera_sensor = None
        self._latest_frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()

    async def start(self, start: str, end: str) -> dict:
        """Start a driving session: reconstruct scene, spawn vehicle, attach camera."""
        if self._active:
            raise RuntimeError("Session already active")

        self._reconstructor = SceneReconstructor(
            world=self._world,
            carla_map=self._map,
            api_fetcher=self._api_fetcher,
        )
        recon_result = self._reconstructor.reconstruct(start, end)

        bp_lib = self._world.get_blueprint_library()
        vehicle_bps = bp_lib.filter("vehicle.tesla.model3")
        if not vehicle_bps:
            raise RuntimeError("Vehicle blueprint not found")

        spawn_points = self._map.get_spawn_points()
        if not spawn_points:
            raise RuntimeError("No spawn points available")

        self.vehicle = self._world.try_spawn_actor(vehicle_bps[0], spawn_points[0])
        if self.vehicle is None:
            raise RuntimeError("Failed to spawn vehicle")

        # Attach RGB camera sensor to the vehicle
        self._attach_camera(bp_lib)

        self._active = True
        self.active_camera = "chase"

        logger.info(
            "Drive session started: vehicle=%d, objects=%d",
            self.vehicle.id, len(recon_result.spawned_actors),
        )

        return {
            "type": "session_ready",
            "vehicle_id": self.vehicle.id,
            "objects_count": len(recon_result.spawned_actors),
        }

    def _attach_camera(self, bp_lib):
        """Attach an RGB camera sensor to the vehicle for streaming frames."""
        try:
            import carla
            camera_bp = bp_lib.find("sensor.camera.rgb")
            if camera_bp is None:
                logger.warning("sensor.camera.rgb blueprint not found")
                return

            # Set camera resolution — lower for streaming performance
            camera_bp.set_attribute("image_size_x", "960")
            camera_bp.set_attribute("image_size_y", "540")
            camera_bp.set_attribute("fov", "90")
            camera_bp.set_attribute("sensor_tick", "0.05")  # 20 FPS

            # Initial transform: chase camera
            cam_transform = carla.Transform(
                carla.Location(x=-8.0, z=4.0),
                carla.Rotation(pitch=-15.0),
            )

            self._camera_sensor = self._world.spawn_actor(
                camera_bp, cam_transform, attach_to=self.vehicle
            )
            self._camera_sensor.listen(self._on_camera_frame)
            logger.info("Camera sensor attached (960x540 @ 20fps)")
        except ImportError:
            logger.info("CARLA not available — camera sensor skipped (mock mode)")
        except Exception as e:
            logger.warning("Failed to attach camera sensor: %s", e)

    def _on_camera_frame(self, image):
        """Callback from CARLA camera sensor — encode frame to JPEG."""
        try:
            # Convert CARLA image to numpy array
            array = np.frombuffer(image.raw_data, dtype=np.uint8)
            array = array.reshape((image.height, image.width, 4))  # BGRA
            rgb = array[:, :, :3][:, :, ::-1]  # BGRA → RGB

            # Encode to JPEG
            pil_image = Image.fromarray(rgb)
            buffer = io.BytesIO()
            pil_image.save(buffer, format="JPEG", quality=70)
            jpeg_bytes = buffer.getvalue()

            with self._frame_lock:
                self._latest_frame = jpeg_bytes
        except Exception as e:
            logger.debug("Frame encode error: %s", e)

    def get_latest_frame(self) -> Optional[bytes]:
        """Get the most recent JPEG frame (thread-safe)."""
        with self._frame_lock:
            return self._latest_frame

    def apply_control(self, steer: float, throttle: float, brake: float, reverse: bool = False) -> dict:
        """Apply vehicle control and return telemetry."""
        if not self._active or self.vehicle is None:
            raise RuntimeError("No active session")

        try:
            import carla
            control = carla.VehicleControl(
                steer=max(-1.0, min(1.0, steer)),
                throttle=max(0.0, min(1.0, throttle)),
                brake=max(0.0, min(1.0, brake)),
                reverse=reverse,
            )
        except ImportError:
            from tests.conftest import MockVehicleControl
            control = MockVehicleControl(
                steer=max(-1.0, min(1.0, steer)),
                throttle=max(0.0, min(1.0, throttle)),
                brake=max(0.0, min(1.0, brake)),
                reverse=reverse,
            )

        self.vehicle.apply_control(control)

        # Update camera position based on active view
        self._update_camera_transform()

        transform = self.vehicle.get_transform()
        velocity = self.vehicle.get_velocity()
        speed_ms = math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
        speed_kmh = speed_ms * 3.6

        return {
            "type": "telemetry",
            "speed": round(speed_kmh, 1),
            "gear": getattr(self.vehicle.get_control(), "gear", 0),
            "pos": [
                round(transform.location.x, 2),
                round(transform.location.y, 2),
                round(transform.location.z, 2),
            ],
            "rot": [
                round(transform.rotation.pitch, 2),
                round(transform.rotation.yaw, 2),
                round(transform.rotation.roll, 2),
            ],
            "steer": round(steer, 3),
            "throttle": round(throttle, 3),
            "brake": round(brake, 3),
        }

    def _update_camera_transform(self):
        """Move the camera sensor to match the active view."""
        if self._camera_sensor is None or self.vehicle is None:
            return
        try:
            import carla
            configs = {
                "chase": carla.Transform(carla.Location(x=-8.0, z=4.0), carla.Rotation(pitch=-15.0)),
                "hood": carla.Transform(carla.Location(x=0.5, z=1.5), carla.Rotation(pitch=0.0)),
                "bird": carla.Transform(carla.Location(x=0.0, z=25.0), carla.Rotation(pitch=-90.0)),
                "free": carla.Transform(carla.Location(x=-5.0, z=3.0), carla.Rotation(pitch=-10.0)),
            }
            new_transform = configs.get(self.active_camera, configs["chase"])
            self._camera_sensor.set_transform(new_transform)
        except Exception:
            pass

    def respawn(self) -> dict:
        """Teleport the vehicle to a random spawn point on the road."""
        if not self._active or self.vehicle is None:
            raise RuntimeError("No active session")

        import random
        spawn_points = self._map.get_spawn_points()
        if not spawn_points:
            raise RuntimeError("No spawn points available")

        new_spawn = random.choice(spawn_points)
        self.vehicle.set_transform(new_spawn)

        # Zero out velocity so the car doesn't keep flying
        try:
            import carla
            self.vehicle.set_target_velocity(carla.Vector3D(0, 0, 0))
        except Exception:
            pass

        transform = self.vehicle.get_transform()
        logger.info("Vehicle respawned at (%.1f, %.1f, %.1f)",
                     transform.location.x, transform.location.y, transform.location.z)

        return {
            "type": "respawned",
            "pos": [
                round(transform.location.x, 2),
                round(transform.location.y, 2),
                round(transform.location.z, 2),
            ],
        }

    def switch_camera(self, view: str) -> None:
        """Switch the active camera view."""
        if view not in VALID_CAMERA_VIEWS:
            raise ValueError(f"Invalid camera view: {view}. Must be one of {VALID_CAMERA_VIEWS}")
        self.active_camera = view
        self._update_camera_transform()

    def end(self) -> dict:
        """End the session: destroy camera, vehicle, cleanup scene."""
        if self._camera_sensor is not None:
            try:
                self._camera_sensor.stop()
                self._camera_sensor.destroy()
            except Exception:
                pass
            self._camera_sensor = None

        if self.vehicle is not None:
            self.vehicle.destroy()
            self.vehicle = None

        if self._reconstructor is not None:
            self._reconstructor.cleanup()
            self._reconstructor = None

        self._active = False
        self._latest_frame = None
        logger.info("Drive session ended")
        return {"type": "session_ended"}

    @property
    def is_active(self) -> bool:
        return self._active


async def handle_message(session: DriveSession, msg: dict) -> dict:
    """Route an incoming WebSocket message to the appropriate session method."""
    msg_type = msg.get("type", "")

    try:
        if msg_type == "start_session":
            return await session.start(start=msg["start"], end=msg["end"])
        elif msg_type == "control":
            return session.apply_control(
                steer=float(msg.get("s", 0)),
                throttle=float(msg.get("t", 0)),
                brake=float(msg.get("b", 0)),
                reverse=bool(msg.get("rev", False)),
            )
        elif msg_type == "camera_switch":
            session.switch_camera(msg["view"])
            return {"type": "camera_switched", "view": msg["view"]}
        elif msg_type == "respawn":
            return session.respawn()
        elif msg_type == "end_session":
            return session.end()
        else:
            return {"type": "error", "message": f"Unknown message type: {msg_type}"}
    except Exception as e:
        logger.error("Error handling message type=%s: %s", msg_type, e, exc_info=True)
        return {"type": "error", "message": str(e)}


async def serve_drive(websocket, world, carla_map, api_fetcher):
    """
    Handle a single WebSocket connection for driving.

    Runs two concurrent loops:
    1. Message handler: reads control input, sends telemetry as JSON
    2. Frame streamer: sends JPEG frames as binary WebSocket messages
    """
    session = DriveSession(world=world, carla_map=carla_map, api_fetcher=api_fetcher)
    frame_task = None

    async def stream_frames():
        """Send MJPEG frames at ~20fps as binary WebSocket messages."""
        last_frame_id = None
        while session.is_active:
            frame = session.get_latest_frame()
            if frame is not None and frame is not last_frame_id:
                try:
                    await websocket.send(frame)  # binary message
                    last_frame_id = frame
                except Exception:
                    break
            await asyncio.sleep(0.05)  # 20fps cap

    try:
        async for raw_message in websocket:
            # Only process text messages (JSON). Binary messages from client are ignored.
            if isinstance(raw_message, bytes):
                continue

            msg = json.loads(raw_message)
            response = await handle_message(session, msg)
            await websocket.send(json.dumps(response))

            # Start frame streaming once session is active
            if session.is_active and frame_task is None:
                frame_task = asyncio.create_task(stream_frames())

    except Exception as e:
        logger.error("WebSocket connection error: %s", e)
    finally:
        if frame_task is not None:
            frame_task.cancel()
            try:
                await frame_task
            except asyncio.CancelledError:
                pass
        if session.is_active:
            session.end()
            logger.info("Session cleaned up after disconnect")
