#!/usr/bin/env python3
# Copyright 2022 Martin Kalcok
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm the service.

Refer to the following post for a quick-start guide that will help you
develop a new k8s charm using the Operator Framework:

    https://discourse.charmhub.io/t/4208
"""

import logging
import os
from typing import Any, Dict, Optional

from charmhelpers.core import hookenv
from charmhelpers.fetch import snap
from ops.charm import CharmBase, ConfigChangedEvent, InstallEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, ModelError
from prometheus_interface.operator import (
    PrometheusConfigError,
    PrometheusConnected,
    PrometheusScrapeTarget,
)

from exporter import ExporterConfigError, ExporterSnap

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


class JujuMachineExporterCharm(CharmBase):
    """Charm the service."""

    # Mapping between charm and snap configuration options
    SNAP_CONFIG_MAP = {
        "controller-url": "controller",
        "juju-user": "user",
        "juju-password": "password",
        "scrape-interval": "refresh",
        "scrape-port": "port",
    }

    def __init__(self, *args: Any) -> None:
        """Initialize charm."""
        super().__init__(*args)
        self.exporter = ExporterSnap()
        self.prometheus_target = PrometheusScrapeTarget(self, "prometheus-scrape")
        self._snap_path: Optional[str] = None
        self._snap_path_set = False

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(
            self.prometheus_target.on.prometheus_available, self._on_prometheus_available
        )

    @property
    def snap_path(self) -> Optional[str]:
        """Get local path to exporter snap.

        If this charm has snap file for the exporter attached as a resource, this property returns
        path to the snap file. If the resource was not attached of the file is empty, this property
        returns None.
        """
        if not self._snap_path_set:
            try:
                self._snap_path = str(self.model.resources.fetch("exporter-snap"))
                # Don't return path to empty resource file
                if not os.path.getsize(self._snap_path) > 0:
                    self._snap_path = None
            except ModelError:
                self._snap_path = None
            finally:
                self._snap_path_set = True

        return self._snap_path

    def generate_exporter_config(self) -> Dict[str, Any]:
        """Generate exporter service config based on the values from charm config."""
        exporter_config = {}
        for charm_option, snap_option in self.SNAP_CONFIG_MAP.items():
            value = self.config[charm_option]
            if not value:
                continue

            exporter_config[snap_option] = value

        return exporter_config

    def reconfigure_scrape_target(self) -> None:
        """Update scrape target configuration in related Prometheus application.

        Note: this function has no effect if there's no application related via
        'prometheus-scrape'.
        """
        port = self.config["scrape-port"]
        interval_minutes = self.config["scrape-interval"]
        interval = interval_minutes * 60
        timeout = self.config["scrape-timeout"]
        try:
            self.prometheus_target.expose_scrape_target(
                port, "/metrics", scrape_interval=f"{interval}s", scrape_timeout=f"{timeout}s"
            )
        except PrometheusConfigError as exc:
            logger.error("Failed to configure prometheus scrape target: %s", exc)
            raise exc

    def reconfigure_open_ports(self) -> None:
        """Update ports that juju shows as 'opened' in units' status."""
        new_port = self.config["scrape-port"]

        for port_spec in hookenv.opened_ports():
            old_port, protocol = port_spec.split("/")
            logger.debug("Setting port %s as closed.", old_port)
            hookenv.close_port(old_port, protocol)

        logger.debug("Setting port %s as opened.", new_port)
        hookenv.open_port(new_port)

    def _on_install(self, _: InstallEvent) -> None:
        """Install juju-machine-exporter snap."""
        self.unit.status = MaintenanceStatus("Installing charm software.")
        try:
            self.exporter.install(self.snap_path)
        except snap.CouldNotAcquireLockException as exc:
            install_source = "local resource" if self.snap_path else "snap store"
            logger.error("Failed to install %s from %s.", self.exporter.SNAP_NAME, install_source)
            raise exc

    def _on_config_changed(self, _: ConfigChangedEvent) -> None:
        """Handle changed configuration."""
        logger.info("Processing new charm configuration.")
        exporter_config = self.generate_exporter_config()
        try:
            self.exporter.apply_config(exporter_config)
        except ExporterConfigError as exc:
            logger.error(str(exc))
            self.unit.status = BlockedStatus("Invalid configuration. Please see logs.")
            return

        self.reconfigure_scrape_target()
        self.reconfigure_open_ports()
        self.unit.status = ActiveStatus("Unit is ready")

    def _on_prometheus_available(self, _: PrometheusConnected) -> None:
        """Trigger configuration of a prometheus scrape target."""
        self.reconfigure_scrape_target()


if __name__ == "__main__":  # pragma: nocover
    main(JujuMachineExporterCharm)
