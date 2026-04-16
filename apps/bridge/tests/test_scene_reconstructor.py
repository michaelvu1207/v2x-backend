"""Tests for the scene reconstructor — TDD: write tests first, then implement."""

import json
import pytest
from unittest.mock import patch, MagicMock

from tests.conftest import (
    MockWorld,
    MockMap,
    FakeV2XApi,
    SAMPLE_DETECTIONS,
)


@pytest.mark.unit
class TestSceneReconstructor:
    """Unit tests with mocked CARLA and fake API."""

    def test_reconstruct_spawns_objects(self, mock_world, fake_v2x_api):
        """Given detections in the time range, objects are spawned in CARLA."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        recon = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        result = recon.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        # Should have spawned actors (deduplicated: cone_001 appears twice → use latest)
        assert len(result.spawned_actors) == 2  # cone_001 (deduped) + cone_002
        assert result.total_detections >= 2

    def test_deduplication_uses_latest(self, mock_world, fake_v2x_api):
        """When same object_id appears multiple times, use the latest detection."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        recon = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        result = recon.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        # traffic_cone_001 has two entries; should use the one with timestamp 17:08:45
        cone_001 = [o for o in result.objects if o["object_id"] == "traffic_cone_001"]
        assert len(cone_001) == 1
        assert cone_001[0]["timestamp_utc"] == "2026-03-22T17:08:45Z"

    def test_empty_timeframe_returns_empty(self, mock_world, empty_v2x_api):
        """No detections in the time range → empty result, no actors spawned."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        recon = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=empty_v2x_api.get_detections_range,
        )
        result = recon.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        assert len(result.spawned_actors) == 0
        assert result.total_detections == 0

    def test_api_failure_raises_clear_error(self, mock_world):
        """API failure should raise a descriptive error, not crash silently."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        def failing_api(start, end, limit=500):
            raise ConnectionError("API Gateway timeout")

        recon = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=failing_api,
        )

        with pytest.raises(ConnectionError, match="API Gateway timeout"):
            recon.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

    def test_cleanup_destroys_all_spawned(self, mock_world, fake_v2x_api):
        """cleanup() should destroy all actors that were spawned by reconstruct()."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        recon = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        result = recon.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")
        assert len(result.spawned_actors) > 0

        recon.cleanup()

        # All spawned actors should be destroyed
        for actor in result.spawned_actors:
            mock_actor = mock_world.get_actor(actor.id)
            assert mock_actor is not None
            assert mock_actor.is_destroyed

    def test_shared_pool_skips_already_spawned(self, mock_world, fake_v2x_api):
        """A second reconstructor sharing the pool should not re-spawn existing objects."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        pool: dict[str, int] = {}

        recon_a = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
            shared_pool=pool,
        )
        result_a = recon_a.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")
        spawned_first = len(result_a.spawned_actors)
        pool_size = len(pool)
        assert spawned_first > 0
        assert pool_size == spawned_first

        spawn_counter_before = len([a for a in mock_world._actors.values() if not a.is_destroyed])

        recon_b = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
            shared_pool=pool,
        )
        result_b = recon_b.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        # Second pass reports the same actors (reused) but spawns no new ones.
        assert len(result_b.spawned_actors) == spawned_first
        assert len(pool) == pool_size
        spawn_counter_after = len([a for a in mock_world._actors.values() if not a.is_destroyed])
        assert spawn_counter_after == spawn_counter_before

    def test_shared_pool_cleanup_is_noop(self, mock_world, fake_v2x_api):
        """When a shared pool is in use, cleanup() must not destroy pool actors."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        pool: dict[str, int] = {}
        recon = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
            shared_pool=pool,
        )
        result = recon.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")
        assert len(pool) > 0

        destroyed = recon.cleanup()
        assert destroyed == 0

        # Pool actors still alive — a concurrent session would see them.
        for actor_id in pool.values():
            actor = mock_world.get_actor(actor_id)
            assert actor is not None
            assert not actor.is_destroyed

    def test_correct_gps_to_carla_conversion(self, mock_world, fake_v2x_api):
        """Objects should be spawned at CARLA coordinates derived from GPS."""
        from digital_twin_bridge.scene_reconstructor import SceneReconstructor

        recon = SceneReconstructor(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        result = recon.reconstruct("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        # Each spawned actor should have a valid transform (not at origin)
        for actor in result.spawned_actors:
            mock_actor = mock_world.get_actor(actor.id)
            assert mock_actor is not None
            # MockMap.geolocation_to_transform returns (100, 200, 0)
            # so actors should be near there
            assert mock_actor._transform is not None
