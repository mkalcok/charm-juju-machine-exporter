# Copyright 2022 Martin Kalcok
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing
"""Unit tests for JujuMachineExporterCharm."""
from itertools import repeat

import pytest

import charm


@pytest.mark.parametrize(
    "event_name, handler",
    [
        ("on.config_changed", "_on_config_changed"),
        ("on.install", "_on_install"),
        ("prometheus_target.on.prometheus_available", "_on_prometheus_available"),
    ],
)
def test_charm_event_mapping(event_name, handler, harness, mocker):
    """Test that all events are bound to the expected event handlers."""
    mocked_handler = mocker.patch.object(harness.charm, handler)

    event = harness.charm
    for object_ in event_name.split("."):
        event = getattr(event, object_)

    event.emit()

    mocked_handler.assert_called_once()


@pytest.mark.parametrize(
    "resource_exists, resource_size, expect_path",
    [
        (False, 0, False),  # In case resource was not attached, return None
        (True, 0, False),  # In case the attached resource is empty file, return None
        (True, 10, True),  # If resource is attached and has size, return local path
    ],
)
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


def test_generate_exporter_config_complete(harness):
    """Test generating complete config file for exporter snap."""
    port = 5000
    controller = "http://juju-controller:9000"
    user = "foo"
    password = "bar"
    interval = 5

    with harness.hooks_disabled():
        harness.update_config(
            {
                "controller-url": controller,
                "juju-user": user,
                "juju-password": password,
                "scrape-interval": interval,
                "scrape-port": port,
            }
        )

    snap_config = harness.charm.generate_exporter_config()

    assert snap_config["controller"] == controller
    assert snap_config["user"] == user
    assert snap_config["password"] == password
    assert snap_config["refresh"] == interval
    assert snap_config["port"] == port


def test_generate_exporter_config_incomplete(harness):
    """Test that generated config won't contain keys for missing ocnfig options ."""
    expected_missing_config = ["controller", "user", "password"]
    expected_present_config = ["refresh", "port"]

    with harness.hooks_disabled():
        harness.update_config(
            {
                "controller-url": "",
                "juju-user": "",
                "juju-password": "",
                "scrape-interval": 5,
                "scrape-port": 5000,
            }
        )

    snap_config = harness.charm.generate_exporter_config()

    for missing_key in expected_missing_config:
        assert missing_key not in snap_config

    for present_key in expected_present_config:
        assert present_key in snap_config


@pytest.mark.parametrize("error", [True, False])
def test_reconfigure_scrape_target(error, harness, mocker):
    """Test updating scrape target of Prometheus."""
    port = 5000
    interval_min = 5
    interval_sec = interval_min * 60
    timeout = 30
    expose_target_mock = mocker.patch.object(
        harness.charm.prometheus_target, "expose_scrape_target"
    )

    with harness.hooks_disabled():
        harness.update_config(
            {"scrape-port": port, "scrape-interval": interval_min, "scrape-timeout": timeout}
        )

    # re-raise error in case the prometheus target configuration fails
    if error:
        expose_target_mock.side_effect = charm.PrometheusConfigError
        with pytest.raises(charm.PrometheusConfigError):
            harness.charm.reconfigure_scrape_target()
    # execute prometheus target reconfiguration
    else:
        harness.charm.reconfigure_scrape_target()
        expose_target_mock.assert_called_once_with(
            port, "/metrics", scrape_interval=f"{interval_sec}s", scrape_timeout=f"{timeout}s"
        )


def test_reconfigure_open_ports(harness, mocker):
    """Test updating which ports are open on units."""
    old_port_spec = "5000/tcp"
    old_port, old_protocol = old_port_spec.split("/")
    new_port = 6000

    mocker.patch.object(charm.hookenv, "opened_ports", return_value=[old_port_spec])
    mock_open_port = mocker.patch.object(charm.hookenv, "open_port")
    mock_close_port = mocker.patch.object(charm.hookenv, "close_port")

    with harness.hooks_disabled():
        harness.update_config({"scrape-port": new_port})

    harness.charm.reconfigure_open_ports()

    mock_close_port.assert_called_once_with(old_port, old_protocol)
    mock_open_port.assert_called_once_with(new_port)


@pytest.mark.parametrize("error", [True, False])
def test_on_install_callback(error, harness, mocker):
    """Test handling of InstallEvent with '_on_install' callback."""
    snap_exception = charm.snap.CouldNotAcquireLockException
    exporter_install = mocker.patch.object(harness.charm.exporter, "install")

    if error:
        exporter_install.side_effect = snap_exception
        with pytest.raises(snap_exception):
            harness.charm._on_install(None)
    else:
        harness.charm._on_install(None)
        exporter_install.assert_called_once_with(harness.charm.snap_path)
        assert isinstance(harness.charm.unit.status, charm.MaintenanceStatus)


def test_on_config_changed_incomplete(harness, mocker):
    """Test what happens when charm has incomplete configuration."""
    incomplete_config = {}
    mocker.patch.object(harness.charm, "generate_exporter_config", return_value=incomplete_config)
    mock_apply_config = mocker.patch.object(
        harness.charm.exporter, "apply_config", side_effect=charm.ExporterConfigError
    )

    harness.charm._on_config_changed(None)

    mock_apply_config.assert_called_once_with(incomplete_config)
    assert isinstance(harness.charm.unit.status, charm.BlockedStatus)


def test_on_config_changed_success(mocker, harness):
    """Test successful application of new config values."""
    valid_config = {"valid": "config"}
    mocker.patch.object(harness.charm, "generate_exporter_config", return_value=valid_config)
    mock_apply_config = mocker.patch.object(harness.charm.exporter, "apply_config")
    mock_reconfigure_scrape = mocker.patch.object(harness.charm, "reconfigure_scrape_target")
    mock_reconfigure_ports = mocker.patch.object(harness.charm, "reconfigure_open_ports")

    harness.charm._on_config_changed(None)

    mock_apply_config.assert_called_once_with(valid_config)
    mock_reconfigure_scrape.assert_called_once_with()
    mock_reconfigure_ports.assert_called_once_with()

    assert isinstance(harness.charm.unit.status, charm.ActiveStatus)


def test_on_prometheus_available(harness, mocker):
    """Test that handler for 'prometheus_available' reconfigures scrape target."""
    mock_reconfigure = mocker.patch.object(harness.charm, "reconfigure_scrape_target")

    harness.charm._on_prometheus_available(None)

    mock_reconfigure.assert_called_once_with()
