"""Tests for the Drive Server — TDD: tests first."""

import json
import asyncio
import pytest
from unittest.mock import MagicMock, patch

from tests.conftest import (
    MockWorld,
    MockClient,
    MockWebSocket,
    MockVehicleControl,
    FakeV2XApi,
    SAMPLE_DETECTIONS,
)


@pytest.mark.unit
class TestDriveServerSession:
    """Unit tests for drive session lifecycle with mocked CARLA."""

    @pytest.mark.asyncio
    async def test_start_session_spawns_vehicle(self, mock_world, fake_v2x_api):
        """start_session should spawn a vehicle and return session_ready."""
        from digital_twin_bridge.drive_server import DriveSession

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        result = await session.start(
            start="2026-03-22T17:00:00Z",
            end="2026-03-22T17:30:00Z",
        )

        assert result["type"] == "session_ready"
        assert result["vehicle_id"] is not None
        assert result["objects_count"] >= 0
        assert session.vehicle is not None

    @pytest.mark.asyncio
    async def test_apply_control(self, mock_world, fake_v2x_api):
        """Control messages should apply to the vehicle and return telemetry."""
        from digital_twin_bridge.drive_server import DriveSession

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        await session.start("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        telemetry = session.apply_control(steer=-0.5, throttle=0.8, brake=0.0)

        assert telemetry["type"] == "telemetry"
        assert "speed" in telemetry
        assert "pos" in telemetry
        assert "rot" in telemetry

        # Verify control was actually applied to the vehicle
        ctrl = session.vehicle.get_control()
        assert ctrl.steer == pytest.approx(-0.5, abs=1e-6)
        assert ctrl.throttle == pytest.approx(0.8, abs=1e-6)
        assert ctrl.brake == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_end_session_cleans_up(self, mock_world, fake_v2x_api):
        """end_session should destroy vehicle, cleanup scene, restore settings."""
        from digital_twin_bridge.drive_server import DriveSession

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        await session.start("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")
        vehicle_id = session.vehicle.id

        session.end()

        # Vehicle should be destroyed
        vehicle = mock_world.get_actor(vehicle_id)
        assert vehicle.is_destroyed
        assert session.vehicle is None

    @pytest.mark.asyncio
    async def test_control_before_start_raises(self, mock_world, fake_v2x_api):
        """Sending control before session starts should raise an error."""
        from digital_twin_bridge.drive_server import DriveSession

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )

        with pytest.raises(RuntimeError, match="No active session"):
            session.apply_control(steer=0, throttle=0, brake=0)

    @pytest.mark.asyncio
    async def test_double_start_raises(self, mock_world, fake_v2x_api):
        """Starting a session while one is active should raise an error."""
        from digital_twin_bridge.drive_server import DriveSession

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        await session.start("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        with pytest.raises(RuntimeError, match="Session already active"):
            await session.start("2026-03-22T18:00:00Z", "2026-03-22T18:30:00Z")

    @pytest.mark.asyncio
    async def test_camera_switch(self, mock_world, fake_v2x_api):
        """Camera switch should update the active camera view."""
        from digital_twin_bridge.drive_server import DriveSession

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        await session.start("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        session.switch_camera("hood")
        assert session.active_camera == "hood"

        session.switch_camera("bird")
        assert session.active_camera == "bird"

    @pytest.mark.asyncio
    async def test_invalid_camera_view_raises(self, mock_world, fake_v2x_api):
        """Switching to an invalid camera view should raise."""
        from digital_twin_bridge.drive_server import DriveSession

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        await session.start("2026-03-22T17:00:00Z", "2026-03-22T17:30:00Z")

        with pytest.raises(ValueError, match="Invalid camera view"):
            session.switch_camera("invalid_view")


@pytest.mark.unit
class TestDriveServerMessageHandling:
    """Test WebSocket message parsing and routing."""

    @pytest.mark.asyncio
    async def test_handle_start_session_message(self, mock_world, fake_v2x_api):
        """A start_session message should trigger session start."""
        from digital_twin_bridge.drive_server import DriveSession, handle_message

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        msg = {"type": "start_session", "start": "2026-03-22T17:00:00Z", "end": "2026-03-22T17:30:00Z"}
        response = await handle_message(session, msg)

        assert response["type"] == "session_ready"

    @pytest.mark.asyncio
    async def test_handle_control_message(self, mock_world, fake_v2x_api):
        """A control message should return telemetry."""
        from digital_twin_bridge.drive_server import DriveSession, handle_message

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        await handle_message(session, {
            "type": "start_session",
            "start": "2026-03-22T17:00:00Z",
            "end": "2026-03-22T17:30:00Z",
        })

        response = await handle_message(session, {
            "type": "control",
            "s": 0.3,
            "t": 0.7,
            "b": 0.0,
        })

        assert response["type"] == "telemetry"

    @pytest.mark.asyncio
    async def test_handle_end_session_message(self, mock_world, fake_v2x_api):
        """An end_session message should clean up and confirm."""
        from digital_twin_bridge.drive_server import DriveSession, handle_message

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        await handle_message(session, {
            "type": "start_session",
            "start": "2026-03-22T17:00:00Z",
            "end": "2026-03-22T17:30:00Z",
        })

        response = await handle_message(session, {"type": "end_session"})
        assert response["type"] == "session_ended"
        assert session.vehicle is None

    @pytest.mark.asyncio
    async def test_handle_unknown_message_type(self, mock_world, fake_v2x_api):
        """Unknown message types should return an error."""
        from digital_twin_bridge.drive_server import DriveSession, handle_message

        session = DriveSession(
            world=mock_world,
            carla_map=mock_world.get_map(),
            api_fetcher=fake_v2x_api.get_detections_range,
        )
        response = await handle_message(session, {"type": "bogus"})
        assert response["type"] == "error"
        assert "unknown" in response["message"].lower() or "Unknown" in response["message"]
