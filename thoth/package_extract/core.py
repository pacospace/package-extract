#!/usr/bin/env python3
# thoth-package-extract
# Copyright(C) 2018, 2019 Fridolin Pokorny
#
# This program is free software: you can redistribute it and / or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""Implementation of core routines for thoth-package-extract."""

import logging
import os
import tempfile
import typing
from shlex import quote

from prometheus_client import CollectorRegistry, pushadd_to_gateway, Gauge

from .handlers import HandlerBase
from .image import construct_rootfs
from .image import download_image
from .image import run_analyzers

_LOGGER = logging.getLogger(__name__)


def extract_buildlog(input_text: str) -> typing.List[dict]:
    """Extract Docker image build log and get all installed packages based on ecosystem."""
    result = []
    for handler in HandlerBase.instantiate_handlers():
        result.append(
            {
                "handler": handler.__class__.__name__.lower(),
                "result": handler.run(input_text),
            }
        )

    return result


def extract_image(
    image_name: str,
    timeout: int = None,
    *,
    registry_credentials: str = None,
    tls_verify: bool = True,
) -> dict:
    """Extract dependencies from an image."""
    # Setting up the prometheus registry and the Gauge metric
    prometheus_registry = CollectorRegistry()
    metric_analyzer_job = Gauge(
        "package_extract_time",
        "Runtime of package extract job",
        registry=prometheus_registry,
    )

    # Begins a timer to record the running time of the job
    with metric_analyzer_job.time(), tempfile.TemporaryDirectory() as dir_path:
        image_name = quote(image_name)
        download_image(
            image_name,
            dir_path,
            timeout=timeout or None,
            registry_credentials=registry_credentials or None,
            tls_verify=tls_verify,
        )
        rootfs_path = os.path.join(dir_path, "rootfs")
        layers = construct_rootfs(dir_path, rootfs_path)

        result = run_analyzers(rootfs_path)
        result["layers"] = layers

    _PUSH_GATEWAY_HOST = os.getenv("PROMETHEUS_PUSHGATEWAY_HOST")
    _PUSH_GATEWAY_PORT = os.getenv("PROMETHEUS_PUSHGATEWAY_PORT")
    if _PUSH_GATEWAY_HOST and _PUSH_GATEWAY_PORT:
        try:
            push_gateway = f"{_PUSH_GATEWAY_HOST:_PUSH_GATEWAY_PORT}"
            _LOGGER.debug(
                f"Submitting metrics to Prometheus push gateway {push_gateway}"
            )
            pushadd_to_gateway(
                push_gateway,
                job="package-extract-runtime",
                registry=prometheus_registry,
            )
        except Exception as e:
            _LOGGER.exception(
                "An error occurred pushing the metrics: {}".format(str(e))
            )

    return result
