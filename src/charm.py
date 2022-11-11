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

from exporter import ExporterConfigError, ExporterSnap

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


class JujuMachineExporterCharm(CharmBase):
    """Charm the service."""

    CONFIG_MAP = {
        "controller-url": "controller",
        "juju-user": "user",
        "juju-password": "password",
        "scrape-interval": "refresh",
        "scrape-port": "port",
    }

    def __init__(self, *args: Any) -> None:
        """Initialize charm."""
        super().__init__(*args)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)

        self.exporter = ExporterSnap()

        self._snap_path: Optional[str] = None
        self._snap_path_set = False

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
        for charm_option, snap_option in self.CONFIG_MAP.items():
            value = self.config[charm_option]
            if not value:
                continue

            exporter_config[snap_option] = value

        return exporter_config

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

        hookenv.open_port(exporter_config["port"])
        self.unit.status = ActiveStatus("Unit is ready")


if __name__ == "__main__":  # pragma: nocover
    main(JujuMachineExporterCharm)
