"""Tests for CARLA connection startup behavior."""

import pytest

from digital_twin_bridge.config import Config
from digital_twin_bridge.carla_connection import CarlaConnection
import digital_twin_bridge.carla_connection as carla_connection_module
from tests.conftest import MockClient, MockMap, MockWorld


@pytest.mark.unit
class TestCarlaConnectionMapSelection:
    def test_connect_loads_configured_map_when_available(self, monkeypatch):
        world = MockWorld()
        world._map = MockMap("Richmond_Field_Station_Richmond_CA")
        client = MockClient(world)
        client.available_maps = [
            "Richmond_Field_Station_Richmond_CA",
            "San_Ramon",
        ]
        monkeypatch.setattr(
            carla_connection_module.carla,
            "Client",
            lambda host, port: client,
        )

        conn = CarlaConnection(Config(CARLA_MAP="San_Ramon"))
        conn.connect()

        assert client.loaded_maps == ["San_Ramon"]
        assert conn.carla_map.name == "San_Ramon"
        assert conn.world.get_settings().synchronous_mode is True

        conn.disconnect()

    def test_connect_keeps_current_map_when_requested_map_unavailable(self, monkeypatch):
        world = MockWorld()
        world._map = MockMap("Richmond_Field_Station_Richmond_CA")
        client = MockClient(world)
        client.available_maps = ["Richmond_Field_Station_Richmond_CA"]
        monkeypatch.setattr(
            carla_connection_module.carla,
            "Client",
            lambda host, port: client,
        )

        conn = CarlaConnection(Config(CARLA_MAP="San_Ramon"))
        conn.connect()

        assert client.loaded_maps == []
        assert conn.carla_map.name == "Richmond_Field_Station_Richmond_CA"
        assert conn.world.get_settings().synchronous_mode is True

        conn.disconnect()
