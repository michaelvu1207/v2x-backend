"""
Scene Reconstructor — queries historical V2X detections and spawns
them as CARLA actors to recreate a past scene.

Reuses geo_utils for GPS-to-CARLA coordinate conversion.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

OBJECT_TYPE_TO_BLUEPRINT = {
    "traffic_cone": "static.prop.trafficcone01",
}
DEFAULT_BLUEPRINT = "static.prop.trafficwarning"


@dataclass
class SpawnedActor:
    """Metadata for an actor spawned during scene reconstruction."""
    id: int
    object_id: str
    object_type: str
    lat: float
    lon: float


@dataclass
class ReconstructionResult:
    """Result of a scene reconstruction."""
    spawned_actors: list[SpawnedActor] = field(default_factory=list)
    objects: list[dict] = field(default_factory=list)
    total_detections: int = 0


class SceneReconstructor:
    """
    Queries the V2X detection API for a time range and spawns
    all detected objects in the CARLA world.
    """

    def __init__(self, world, carla_map, api_fetcher: Callable):
        self._world = world
        self._map = carla_map
        self._api_fetcher = api_fetcher
        self._spawned_actors: list[SpawnedActor] = []

    def reconstruct(self, start: str, end: str, limit: int = 500) -> ReconstructionResult:
        """
        Fetch detections for [start, end] and spawn them in CARLA.
        Deduplicates by object_id keeping the latest detection per object.
        Raises on API failure (no silent swallowing).
        """
        result = ReconstructionResult()

        # 1. Fetch detections
        api_response = self._api_fetcher(start, end, limit)
        items = api_response.get("items", [])
        result.total_detections = len(items)

        if not items:
            logger.info("No detections found for %s to %s", start, end)
            return result

        # 2. Deduplicate by object_id — keep latest timestamp
        deduped: dict[str, dict] = {}
        for item in items:
            oid = item["object_id"]
            if oid not in deduped or item["timestamp_utc"] > deduped[oid]["timestamp_utc"]:
                deduped[oid] = item

        result.objects = list(deduped.values())
        logger.info(
            "Reconstructing scene: %d unique objects from %d detections",
            len(deduped), len(items),
        )

        # 3. Spawn each object in CARLA
        bp_lib = self._world.get_blueprint_library()

        for obj in result.objects:
            obj_type = obj.get("object_type", "unknown")
            bp_id = OBJECT_TYPE_TO_BLUEPRINT.get(obj_type, DEFAULT_BLUEPRINT)
            blueprints = bp_lib.filter(bp_id)
            if not blueprints:
                logger.warning("No blueprint found for %s (%s)", bp_id, obj_type)
                continue
            bp = blueprints[0]

            # GPS to CARLA coordinates via map geo-reference
            gps = obj.get("gps_location", {})
            lat = gps.get("latitude", 0.0)
            lon = gps.get("longitude", 0.0)
            transform = self._gps_to_transform(lat, lon)

            actor = self._world.try_spawn_actor(bp, transform)
            if actor is None:
                logger.warning("Failed to spawn %s at (%.6f, %.6f)", obj_type, lat, lon)
                continue

            spawned = SpawnedActor(
                id=actor.id,
                object_id=obj["object_id"],
                object_type=obj_type,
                lat=lat,
                lon=lon,
            )
            self._spawned_actors.append(spawned)
            result.spawned_actors.append(spawned)

        logger.info("Scene reconstruction complete: %d actors spawned", len(result.spawned_actors))
        return result

    def cleanup(self) -> int:
        """Destroy all actors spawned by this reconstructor."""
        destroyed = 0
        for spawned in self._spawned_actors:
            actor = self._world.get_actor(spawned.id)
            if actor is not None:
                actor.destroy()
                destroyed += 1
        self._spawned_actors.clear()
        return destroyed

    def _gps_to_transform(self, lat: float, lon: float):
        """Convert GPS lat/lon to a CARLA Transform using map geo-reference."""
        # Mirror latitude for UE4 left-handed coordinate system
        origin_geo = self._map.transform_to_geolocation(
            type("L", (), {"x": 0, "y": 0, "z": 0})()
        )
        corrected_lat = 2 * origin_geo.latitude - lat

        geo = type("G", (), {
            "latitude": corrected_lat,
            "longitude": lon,
            "altitude": 0.0,
        })()
        transform = self._map.geolocation_to_transform(geo)

        # Snap to road surface
        waypoint = self._map.get_waypoint(transform.location, project_to_road=True)
        if waypoint:
            transform.location = waypoint.transform.location

        return transform
