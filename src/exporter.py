#!/usr/bin/env python3
# Copyright 2022 Martin Kalcok
# See LICENSE file for licensing details.

"""Exporter snap helper.

Module focused on handling operations related to juju-machine-exporter snap.
"""
import logging
import os
import subprocess
from typing import Any, Dict, Optional

import yaml
from charmhelpers.fetch import snap

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


class ExporterConfigError(Exception):
    """Indicates problem with configuration of exporter service."""


class ExporterSnap:
    """Class that handles operations of juju-machine-exporter snap and related services."""

    # TODO: change snap name  # pylint: disable=fixme
    SNAP_NAME = "test-exporter"
    SNAP_CONFIG_PATH = f"/var/snap/{SNAP_NAME}/current/config/exporter.yaml"
    _SNAP_ACTIONS = [
        "stop",
        "start",
        "restart",
    ]
    _REQUIRED_CONFIG = ["port", "controller", "user", "password", "refresh"]

    def install(self, snap_path: Optional[str] = None) -> None:
        """Install juju-machine-exporter snap.

        This method tries to install snap from local file if parameter :snap_path is provided.
        Otherwise, it'll attempt installation from snap store based on ExporterSnap.SNAP_NAME.

        :param snap_path: Optional parameter to provide local file as source of snap installation.
        :raises:
            snap.CouldNotAcquireLockException: In case of snap installation failure.
        """
        if snap_path:
            logger.info("Installing snap %s from local resource.", self.SNAP_NAME)
            snap.snap_install(snap_path, "--dangerous")
        else:
            logger.info("Installing %s snap from snap store.", self.SNAP_NAME)
            snap.snap_install(self.SNAP_NAME)

    def validate_config(self, config: Dict[str, Any]) -> None:
        """Validate supplied config file for exporter service.

        :param config: config dictionary to be validated
        :raises:
            ExporterConfigError: In case the config does not pass the validation process. For
                example if the required fields are missing or values have unexpected format.
        """
        errors = ""

        # Verify that there are no missing options
        missing_options = [option for option in self._REQUIRED_CONFIG if option not in config]
        if missing_options:
            missing_str = ", ".join(missing_options)
            errors += f"Following config options are missing: {missing_str}{os.linesep}"

        # Verify that 'port' is number within valid port range.
        try:
            port = int(config.get("port", ""))
            if 1 > port > 655535:
                errors += f"Port {port} is not valid port number.{os.linesep}"
        except ValueError:
            errors += f"Configuration option 'port' must be a number.{os.linesep}"

        # Verify that 'refresh' is positive number.
        try:
            refresh = int(config.get("refresh", ""))
            if refresh < 1:
                errors += f"Configuration option 'refresh' must be positive number.{os.linesep}"
        except ValueError:
            errors += f"Configuration option 'refresh' must be a number.{os.linesep}"

        if errors:
            raise ExporterConfigError(errors)

    def apply_config(self, exporter_config: Dict[str, Any]) -> None:
        """Update configuration file for exporter service."""
        self.stop()
        logger.info("Updating exporter service configuration.")
        self.validate_config(exporter_config)

        with open(self.SNAP_CONFIG_PATH, "w", encoding="utf-8") as config_file:
            yaml.safe_dump(exporter_config, config_file)

        self.start()
        logger.info("Exporter configuration updated.")

    def restart(self) -> None:
        """Restart exporter service."""
        self._execute_service_action("restart")

    def stop(self) -> None:
        """Stop exporter service."""
        self._execute_service_action("stop")

    def start(self) -> None:
        """Start exporter service."""
        self._execute_service_action("start")

    def _execute_service_action(self, action: str) -> None:
        """Execute one of the supported snap service actions.

        Supported actions:
            - stop
            - start
            - restart

        :param action: snap service action to execute
        :raises:
            RuntimeError: If requested action is not supported.
        """
        if action not in self._SNAP_ACTIONS:
            raise RuntimeError(f"Snap service action '{action}' is not supported.")
        logger.info("%s service executing action: %s", self.SNAP_NAME, action)
        subprocess.call(["snap", action, self.SNAP_NAME])
