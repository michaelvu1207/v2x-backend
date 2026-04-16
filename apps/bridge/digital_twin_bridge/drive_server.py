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
import websockets
from PIL import Image

from digital_twin_bridge.scene_reconstructor import SceneReconstructor
from digital_twin_bridge.camera_streamer import compute_camera_transform

logger = logging.getLogger(__name__)

VALID_CAMERA_VIEWS = {"chase", "hood", "bird", "free"}

# Default vehicle if none specified
DEFAULT_VEHICLE = "vehicle.tesla.model3"


def get_available_vehicles(world) -> list[dict]:
    """Query CARLA for all spawnable vehicle blueprints."""
    bp_lib = world.get_blueprint_library()
    vehicles = []
    for bp in bp_lib.filter("vehicle.*"):
        bp_id = bp.id
        # Extract make and model from blueprint id (e.g. "vehicle.tesla.model3")
        parts = bp_id.split(".")
        if len(parts) >= 3:
            make = parts[1].title()
            model = parts[2].replace("_", " ").title()
            display_name = f"{make} {model}"
        else:
            display_name = bp_id

        # Get number of wheels to filter out bikes if desired
        num_wheels = 4
        try:
            num_wheels = int(bp.get_attribute("number_of_wheels").recommended_values[0]) if bp.has_attribute("number_of_wheels") else 4
        except Exception:
            pass

        vehicles.append({
            "id": bp_id,
            "name": display_name,
            "wheels": num_wheels,
        })

    # Sort: 4-wheeled first, then alphabetically
    vehicles.sort(key=lambda v: (0 if v["wheels"] >= 4 else 1, v["name"]))
    return vehicles


def get_spawnable_objects(world) -> list[dict]:
    """Query CARLA for all spawnable objects (vehicles + static props)."""
    bp_lib = world.get_blueprint_library()
    objects = []

    # Vehicles (can be placed as parked cars, police cars, etc.)
    for bp in bp_lib.filter("vehicle.*"):
        parts = bp.id.split(".")
        if len(parts) >= 3:
            make = parts[1].title()
            model = parts[2].replace("_", " ").title()
            name = f"{make} {model}"
        else:
            name = bp.id
        objects.append({"id": bp.id, "name": name, "category": "vehicle"})

    # Static props (cones, barriers, signs, etc.)
    for bp in bp_lib.filter("static.prop.*"):
        parts = bp.id.split(".")
        name = parts[-1].replace("_", " ").title() if parts else bp.id
        objects.append({"id": bp.id, "name": name, "category": "prop"})

    # Sort by category then name
    objects.sort(key=lambda o: (0 if o["category"] == "vehicle" else 1, o["name"]))
    return objects


# ── Scenario file I/O ──

import os
import re

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "scenes")


def _ensure_scenes_dir():
    os.makedirs(SCENARIOS_DIR, exist_ok=True)


def _sanitize_name(name: str) -> str:
    """Convert a scenario name to a safe filename slug."""
    slug = re.sub(r"[^a-zA-Z0-9_\- ]", "", name).strip().replace(" ", "_").lower()
    if not slug:
        slug = "untitled"
    return slug


def list_scenarios() -> list[dict]:
    """List all saved scenario files."""
    _ensure_scenes_dir()
    scenarios = []
    for fname in sorted(os.listdir(SCENARIOS_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(SCENARIOS_DIR, fname)
        try:
            with open(fpath) as f:
                data = json.load(f)
            scenarios.append({
                "name": data.get("name", fname.replace(".json", "")),
                "file": fname,
                "object_count": len(data.get("objects", [])),
            })
        except Exception:
            continue
    return scenarios


def save_scenario(name: str, objects: list[dict]) -> dict:
    """Save a scenario to disk."""
    _ensure_scenes_dir()
    slug = _sanitize_name(name)
    fpath = os.path.join(SCENARIOS_DIR, f"{slug}.json")
    data = {"name": name, "objects": objects}
    with open(fpath, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Scenario saved: %s (%d objects) → %s", name, len(objects), fpath)
    return {"type": "scenario_saved", "name": name, "file": f"{slug}.json", "object_count": len(objects)}


def load_scenario(filename: str) -> dict:
    """Load a scenario from disk."""
    fpath = os.path.join(SCENARIOS_DIR, filename)
    if not os.path.isfile(fpath):
        raise FileNotFoundError(f"Scenario file not found: {filename}")
    with open(fpath) as f:
        return json.load(f)


def delete_scenario(filename: str) -> dict:
    """Delete a scenario file."""
    fpath = os.path.join(SCENARIOS_DIR, filename)
    if not os.path.isfile(fpath):
        raise FileNotFoundError(f"Scenario file not found: {filename}")
    os.remove(fpath)
    logger.info("Scenario deleted: %s", filename)
    return {"type": "scenario_deleted", "file": filename}


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
        self._accepting_frames = False  # Guard against callbacks after stop
        self._placed_objects: list = []  # User-placed objects (actor, blueprint_id, pos)

    async def start(self, start: str, end: str, vehicle_blueprint: str = DEFAULT_VEHICLE) -> dict:
        """Start a driving session: reconstruct scene, spawn vehicle, attach camera.

        If any step fails, _force_cleanup() ensures no actors are leaked.
        """
        if self._active:
            raise RuntimeError("Session already active")

        try:
            self._reconstructor = SceneReconstructor(
                world=self._world,
                carla_map=self._map,
                api_fetcher=self._api_fetcher,
            )
            recon_result = self._reconstructor.reconstruct(start, end)

            bp_lib = self._world.get_blueprint_library()
            vehicle_bps = bp_lib.filter(vehicle_blueprint)
            if not vehicle_bps:
                # Fallback to default if selected vehicle not found
                logger.warning("Vehicle '%s' not found, falling back to '%s'", vehicle_blueprint, DEFAULT_VEHICLE)
                vehicle_bps = bp_lib.filter(DEFAULT_VEHICLE)
            if not vehicle_bps:
                raise RuntimeError("Vehicle blueprint not found")

            import random
            spawn_points = self._map.get_spawn_points()
            if not spawn_points:
                raise RuntimeError("No spawn points available")

            random.shuffle(spawn_points)
            self.vehicle = None
            for sp in spawn_points:
                self.vehicle = self._world.try_spawn_actor(vehicle_bps[0], sp)
                if self.vehicle is not None:
                    break
            if self.vehicle is None:
                raise RuntimeError("Failed to spawn vehicle")

            # Physics power cap removed — vehicle runs at stock max_rpm / torque curve.

            # Attach RGB camera sensor to the vehicle
            self._attach_camera(bp_lib)

            self._accepting_frames = True
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
        except Exception:
            # If anything fails during startup, clean up whatever was partially created
            self._force_cleanup()
            raise

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
        if not self._accepting_frames:
            return
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

        # Throttle pass-through — top speed is governed by CARLA vehicle physics,
        # same as PythonAPI/examples/manual_control.py.
        capped_throttle = max(0.0, min(1.0, throttle))

        try:
            import carla
            control = carla.VehicleControl(
                steer=max(-1.0, min(1.0, steer)),
                throttle=capped_throttle,
                brake=max(0.0, min(1.0, brake)),
                reverse=reverse,
            )
        except ImportError:
            from tests.conftest import MockVehicleControl
            control = MockVehicleControl(
                steer=max(-1.0, min(1.0, steer)),
                throttle=capped_throttle,
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

    def spawn_object(self, blueprint_id: str, forward_offset: float = 8.0) -> dict:
        """Spawn an object near the vehicle's current position.

        The object is placed forward_offset meters ahead of the vehicle,
        matching the vehicle's yaw so parked cars face the same direction.
        """
        if not self._active or self.vehicle is None:
            raise RuntimeError("No active session")

        import carla

        bp_lib = self._world.get_blueprint_library()
        bp = bp_lib.find(blueprint_id)
        if bp is None:
            raise ValueError(f"Blueprint not found: {blueprint_id}")

        # Calculate spawn position: forward_offset meters ahead of the vehicle
        vehicle_transform = self.vehicle.get_transform()
        yaw_rad = math.radians(vehicle_transform.rotation.yaw)
        spawn_loc = carla.Location(
            x=vehicle_transform.location.x + forward_offset * math.cos(yaw_rad),
            y=vehicle_transform.location.y + forward_offset * math.sin(yaw_rad),
            z=vehicle_transform.location.z + 0.5,  # slightly above ground to avoid clipping
        )
        spawn_transform = carla.Transform(
            spawn_loc,
            carla.Rotation(yaw=vehicle_transform.rotation.yaw),
        )

        actor = self._world.try_spawn_actor(bp, spawn_transform)
        if actor is None:
            raise RuntimeError(f"Failed to spawn {blueprint_id} — location may be blocked")

        pos = [round(spawn_loc.x, 2), round(spawn_loc.y, 2), round(spawn_loc.z, 2)]
        yaw = round(vehicle_transform.rotation.yaw, 2)
        self._placed_objects.append({
            "actor": actor,
            "blueprint": blueprint_id,
            "pos": pos,
            "yaw": yaw,
        })

        logger.info("Placed object %s (id=%d) at (%.1f, %.1f, %.1f)",
                     blueprint_id, actor.id, spawn_loc.x, spawn_loc.y, spawn_loc.z)

        return {
            "type": "object_spawned",
            "actor_id": actor.id,
            "blueprint": blueprint_id,
            "pos": pos,
            "placed_count": len(self._placed_objects),
        }

    def undo_place(self) -> dict:
        """Remove the most recently placed object."""
        if not self._active:
            raise RuntimeError("No active session")
        if not self._placed_objects:
            return {"type": "undo_empty", "message": "No objects to undo"}

        entry = self._placed_objects.pop()
        actor = entry["actor"]
        try:
            actor.destroy()
            logger.info("Undid placement of %s (id=%d)", entry["blueprint"], actor.id)
        except Exception as e:
            logger.warning("Failed to destroy placed object: %s", e)

        return {
            "type": "object_removed",
            "blueprint": entry["blueprint"],
            "pos": entry["pos"],
            "placed_count": len(self._placed_objects),
        }

    def get_placed_snapshot(self) -> list[dict]:
        """Return a serializable snapshot of all placed objects (no actor refs)."""
        return [
            {"blueprint": o["blueprint"], "pos": o["pos"], "yaw": o.get("yaw", 0)}
            for o in self._placed_objects
        ]

    def load_scenario_objects(self, objects: list[dict]) -> dict:
        """Spawn a list of objects from a scenario definition."""
        if not self._active:
            raise RuntimeError("No active session")

        import carla

        bp_lib = self._world.get_blueprint_library()
        spawned = 0
        failed = 0

        for obj in objects:
            bp = bp_lib.find(obj["blueprint"])
            if bp is None:
                logger.warning("Scenario: blueprint not found: %s", obj["blueprint"])
                failed += 1
                continue

            pos = obj["pos"]
            yaw = obj.get("yaw", 0)
            transform = carla.Transform(
                carla.Location(x=pos[0], y=pos[1], z=pos[2]),
                carla.Rotation(yaw=yaw),
            )

            actor = self._world.try_spawn_actor(bp, transform)
            if actor is None:
                logger.warning("Scenario: failed to spawn %s at %s", obj["blueprint"], pos)
                failed += 1
                continue

            self._placed_objects.append({
                "actor": actor,
                "blueprint": obj["blueprint"],
                "pos": pos,
                "yaw": yaw,
            })
            spawned += 1

        logger.info("Scenario loaded: %d spawned, %d failed", spawned, failed)
        return {
            "type": "scenario_loaded",
            "spawned": spawned,
            "failed": failed,
            "placed_count": len(self._placed_objects),
        }

    def set_camera_settings(self, params: dict) -> dict:
        """Update camera sensor post-processing attributes at runtime.

        Destroys the current camera sensor and respawns it with the new
        attributes, since CARLA does not support changing blueprint
        attributes after spawn.
        """
        if not self._active or self._camera_sensor is None:
            raise RuntimeError("No active session or camera")

        import carla

        # Stop accepting frames during swap
        self._accepting_frames = False

        # Save current transform
        current_transform = self._camera_sensor.get_transform()

        # Stop and destroy old sensor
        try:
            self._camera_sensor.stop()
        except Exception:
            pass
        try:
            self._camera_sensor.destroy()
        except Exception:
            pass

        # Respawn with new attributes
        bp_lib = self._world.get_blueprint_library()
        camera_bp = bp_lib.find("sensor.camera.rgb")

        # Base attributes
        camera_bp.set_attribute("image_size_x", "960")
        camera_bp.set_attribute("image_size_y", "540")
        camera_bp.set_attribute("sensor_tick", "0.05")

        # Apply all provided settings
        for key, value in params.items():
            try:
                camera_bp.set_attribute(key, str(value))
            except Exception as e:
                logger.debug("Camera attribute '%s' failed: %s", key, e)

        self._camera_sensor = self._world.spawn_actor(
            camera_bp, current_transform, attach_to=self.vehicle
        )
        self._camera_sensor.listen(self._on_camera_frame)
        self._accepting_frames = True

        logger.info("Camera settings updated: %d attributes applied", len(params))
        return {"type": "camera_settings_set"}

    def set_weather(self, params: dict) -> dict:
        """Apply weather parameters to the CARLA world."""
        if not self._active:
            raise RuntimeError("No active session")

        import carla

        weather = carla.WeatherParameters(
            cloudiness=float(params.get("cloudiness", 0)),
            precipitation=float(params.get("precipitation", 0)),
            precipitation_deposits=float(params.get("precipitation_deposits", 0)),
            wind_intensity=float(params.get("wind_intensity", 0)),
            sun_azimuth_angle=float(params.get("sun_azimuth_angle", 45)),
            sun_altitude_angle=float(params.get("sun_altitude_angle", 45)),
            fog_density=float(params.get("fog_density", 0)),
            fog_distance=float(params.get("fog_distance", 0)),
            fog_falloff=float(params.get("fog_falloff", 0)),
            wetness=float(params.get("wetness", 0)),
            scattering_intensity=float(params.get("scattering_intensity", 1)),
            mie_scattering_scale=float(params.get("mie_scattering_scale", 0.03)),
            rayleigh_scattering_scale=float(params.get("rayleigh_scattering_scale", 0.0331)),
            dust_storm=float(params.get("dust_storm", 0)),
        )
        self._world.set_weather(weather)
        logger.info("Weather updated: sun_alt=%.0f, cloud=%.0f, rain=%.0f",
                     weather.sun_altitude_angle, weather.cloudiness, weather.precipitation)
        return {"type": "weather_set"}

    def sync_v2x_zones(self, zones: list[dict]) -> dict:
        """Draw V2X zone outlines + hatching on the CARLA ground.

        Each zone is a dict with 'polygon' (list of [lon, lat] pairs),
        'signal_type', and 'color'. Lines are drawn at ground level
        with a 6s lifetime (redrawn periodically by the frontend).
        """
        if not self._active:
            raise RuntimeError("No active session")

        import carla
        from digital_twin_bridge.geo_utils import gps_to_carla

        COLORS = {
            "warning": carla.Color(255, 60, 60, 255),
            "alert": carla.Color(255, 150, 50, 255),
            "info": carla.Color(60, 130, 255, 255),
        }
        # Dimmer version for hatching
        HATCH_COLORS = {
            "warning": carla.Color(255, 60, 60, 80),
            "alert": carla.Color(255, 150, 50, 80),
            "info": carla.Color(60, 130, 255, 80),
        }

        drawn = 0
        for zone in zones:
            polygon = zone.get("polygon", [])
            if len(polygon) < 3:
                continue

            sig_type = zone.get("signal_type", "warning")
            color = COLORS.get(sig_type, COLORS["warning"])
            hatch_color = HATCH_COLORS.get(sig_type, HATCH_COLORS["warning"])

            # Convert GPS polygon vertices to CARLA locations at ground level
            carla_points = []
            for lon, lat in polygon:
                try:
                    loc = gps_to_carla(self._map, lat, lon)
                    loc.z += 0.15
                    carla_points.append(loc)
                except Exception:
                    continue

            if len(carla_points) < 3:
                continue

            # Draw outline
            for i in range(len(carla_points)):
                start = carla_points[i]
                end = carla_points[(i + 1) % len(carla_points)]
                self._world.debug.draw_line(
                    start, end,
                    thickness=0.15,
                    color=color,
                    life_time=6.0,
                )

            # Draw diagonal hatching inside the polygon
            hatches = self._compute_hatching(carla_points, spacing=2.0)
            for h_start, h_end in hatches:
                self._world.debug.draw_line(
                    h_start, h_end,
                    thickness=0.08,
                    color=hatch_color,
                    life_time=6.0,
                )

            drawn += 1

        return {"type": "v2x_zones_synced", "drawn": drawn}

    @staticmethod
    def _compute_hatching(carla_points, spacing=2.0):
        """Generate diagonal hatching line segments inside a polygon.

        Uses a scanline approach: sweeps 45-degree lines across the
        polygon bounding box and clips them to the polygon boundary.
        """
        import carla

        if len(carla_points) < 3:
            return []

        xs = [p.x for p in carla_points]
        ys = [p.y for p in carla_points]
        avg_z = sum(p.z for p in carla_points) / len(carla_points)

        # Diagonal scanline: y = x + c
        # Range of c: (min_y - max_x) to (max_y - min_x)
        c_min = min(ys) - max(xs)
        c_max = max(ys) - min(xs)

        # Build edge list as (x1,y1,x2,y2) for intersection tests
        n = len(carla_points)
        edges = []
        for i in range(n):
            p1 = carla_points[i]
            p2 = carla_points[(i + 1) % n]
            edges.append((p1.x, p1.y, p2.x, p2.y))

        segments = []
        step = spacing * 1.414  # diagonal spacing
        c = c_min + step
        while c < c_max:
            # Find intersections of y = x + c with each edge
            intersections = []
            for x1, y1, x2, y2 in edges:
                dx = x2 - x1
                dy = y2 - y1
                # Parametric: P = (x1,y1) + t*(dx,dy)
                # Scanline: y = x + c => y1 + t*dy = x1 + t*dx + c
                denom = dy - dx
                if abs(denom) < 1e-10:
                    continue
                t = (x1 - y1 + c) / denom
                if t < 0.0 or t > 1.0:
                    continue
                ix = x1 + t * dx
                intersections.append(ix)

            # Sort and pair up (entry/exit)
            intersections.sort()
            for i in range(0, len(intersections) - 1, 2):
                sx = intersections[i]
                ex = intersections[i + 1]
                segments.append((
                    carla.Location(x=sx, y=sx + c, z=avg_z),
                    carla.Location(x=ex, y=ex + c, z=avg_z),
                ))
            c += step

        return segments

    def switch_camera(self, view: str) -> None:
        """Switch the active camera view."""
        if view not in VALID_CAMERA_VIEWS:
            raise ValueError(f"Invalid camera view: {view}. Must be one of {VALID_CAMERA_VIEWS}")
        self.active_camera = view
        self._update_camera_transform()

    def end(self) -> dict:
        """End the session: destroy camera, vehicle, cleanup scene."""
        self._force_cleanup()
        logger.info("Drive session ended")
        return {"type": "session_ended"}

    def _force_cleanup(self):
        """
        Unconditionally destroy all owned CARLA actors.
        Safe to call multiple times. Each resource has its own try/except
        so one failure doesn't prevent cleanup of the rest.
        """
        # Stop accepting frames first to prevent callback race
        self._accepting_frames = False
        self._active = False

        # Camera sensor: stop and destroy in separate try blocks
        if self._camera_sensor is not None:
            try:
                self._camera_sensor.stop()
            except Exception as e:
                logger.debug("Camera stop failed (may already be stopped): %s", e)
            try:
                self._camera_sensor.destroy()
            except Exception as e:
                logger.warning("Camera destroy failed: %s", e)
            self._camera_sensor = None

        # Vehicle
        if self.vehicle is not None:
            try:
                self.vehicle.destroy()
            except Exception as e:
                logger.warning("Vehicle destroy failed: %s", e)
            self.vehicle = None

        # User-placed objects
        for entry in self._placed_objects:
            try:
                entry["actor"].destroy()
            except Exception as e:
                logger.debug("Placed object destroy failed: %s", e)
        self._placed_objects.clear()

        # Scene objects
        if self._reconstructor is not None:
            try:
                self._reconstructor.cleanup()
            except Exception as e:
                logger.warning("Scene cleanup failed: %s", e)
            self._reconstructor = None

        self._latest_frame = None

    @property
    def is_active(self) -> bool:
        return self._active


async def handle_message(session: DriveSession, msg: dict) -> dict:
    """Route an incoming WebSocket message to the appropriate session method."""
    msg_type = msg.get("type", "")

    try:
        if msg_type == "list_vehicles":
            vehicles = get_available_vehicles(session._world)
            return {"type": "vehicle_list", "vehicles": vehicles}
        elif msg_type == "list_objects":
            objects = get_spawnable_objects(session._world)
            return {"type": "object_list", "objects": objects}
        elif msg_type == "spawn_object":
            return session.spawn_object(
                blueprint_id=msg["blueprint"],
                forward_offset=float(msg.get("offset", 8.0)),
            )
        elif msg_type == "undo_place":
            return session.undo_place()
        elif msg_type == "list_scenarios":
            return {"type": "scenario_list", "scenarios": list_scenarios()}
        elif msg_type == "save_scenario":
            snapshot = session.get_placed_snapshot()
            if not snapshot:
                return {"type": "error", "message": "No objects placed to save"}
            return save_scenario(name=msg["name"], objects=snapshot)
        elif msg_type == "load_scenario":
            data = load_scenario(msg["file"])
            return session.load_scenario_objects(data.get("objects", []))
        elif msg_type == "delete_scenario":
            return delete_scenario(msg["file"])
        elif msg_type == "start_session":
            vehicle_bp = msg.get("vehicle", DEFAULT_VEHICLE)
            return await session.start(
                start=msg["start"],
                end=msg["end"],
                vehicle_blueprint=vehicle_bp,
            )
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
        elif msg_type == "set_weather":
            return session.set_weather(msg.get("params", {}))
        elif msg_type == "set_camera_settings":
            return session.set_camera_settings(msg.get("params", {}))
        elif msg_type == "sync_v2x_zones":
            return session.sync_v2x_zones(msg.get("zones", []))
        elif msg_type == "respawn":
            return session.respawn()
        elif msg_type == "end_session":
            return session.end()
        else:
            return {"type": "error", "message": f"Unknown message type: {msg_type}"}
    except Exception as e:
        logger.error("Error handling message type=%s: %s", msg_type, e, exc_info=True)
        return {"type": "error", "message": str(e)}


# Track all active sessions for the periodic actor audit
_active_sessions: list[DriveSession] = []


async def serve_drive(websocket, world, carla_map, api_fetcher):
    """
    Handle a single WebSocket connection for driving.

    Multiplayer: each connection gets its own vehicle, camera, and frame stream
    in the same CARLA world. All players see each other's cars.
    """
    session = DriveSession(world=world, carla_map=carla_map, api_fetcher=api_fetcher)
    frame_task = None
    frame_stop = asyncio.Event()

    async def stream_frames():
        """Send MJPEG frames at ~20fps as binary WebSocket messages."""
        last_frame_id = None
        while not frame_stop.is_set():
            if not session.is_active:
                await asyncio.sleep(0.1)
                continue
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
            if isinstance(raw_message, bytes):
                continue

            msg = json.loads(raw_message)
            response = await handle_message(session, msg)
            await websocket.send(json.dumps(response))

            # Track session and start frame streaming once active
            if session.is_active and session not in _active_sessions:
                _active_sessions.append(session)
            if session.is_active and frame_task is None:
                frame_task = asyncio.create_task(stream_frames())

    except websockets.exceptions.ConnectionClosed:
        logger.info("WebSocket connection closed by client")
    except Exception as e:
        logger.error("WebSocket connection error: %s", e)
    finally:
        frame_stop.set()
        if frame_task is not None:
            frame_task.cancel()
            try:
                await frame_task
            except (asyncio.CancelledError, Exception):
                pass

        session._force_cleanup()
        if session in _active_sessions:
            _active_sessions.remove(session)
        logger.info("Session cleaned up after disconnect")
