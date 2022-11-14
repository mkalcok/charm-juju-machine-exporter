# Copyright 2022 Martin Kalcok
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing
from itertools import repeat

import pytest


@pytest.mark.parametrize("event_name, handler", [
    ("on.config_changed", "_on_config_changed"),
    ("on.install", "_on_install"),
    ("prometheus_target.on.prometheus_available", "_on_prometheus_available"),
])
def test_charm_event_mapping(event_name, handler, harness, mocker):
    """Test that all events are bound to the expected event handlers."""
    mocked_handler = mocker.patch.object(harness.charm, handler)

    event = harness.charm
    for object_ in event_name.split("."):
        event = event.__getattribute__(object_)

    event.emit()

    mocked_handler.assert_called_once()


@pytest.mark.parametrize("resource_exists, resource_size, expect_path", [
    (False, 0, False),  # In case resource was not attached, return None
    (True, 0, False),  # In case the attached resource is empty file, return None
    (True, 10, True),  # If resource is attached and has size, return local path
])
def test_snap_path_property(resource_exists, resource_size, expect_path, harness):
    """Test that 'snap_path' property returns file path only when real resource is attached.

    If resource is not attached or if it's an empty file, this property should return None.
    """
    snap_name = "exporter-snap"
    if resource_exists:
        # Generate some fake data for snap file if it's supposed to have some
        snap_data = "".join(list(repeat("0", resource_size)))
        harness.add_resource(snap_name, snap_data)

    expected_path = str(harness.charm.model.resources.fetch(snap_name)) if expect_path else None

    assert harness.charm.snap_path == expected_path
