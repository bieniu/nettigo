"""Python wrapper for getting air quality data from Nettigo Air Monitor devices."""
from __future__ import annotations

import asyncio
import logging
import re
from http import HTTPStatus
from typing import Any, cast

from aiohttp import ClientConnectorError, ClientResponseError, ClientSession
from dacite import from_dict

from .const import (
    ATTR_CONFIG,
    ATTR_DATA,
    ATTR_OTA,
    ATTR_RESTART,
    ATTR_UPTIME,
    ATTR_VALUES,
    ENDPOINTS,
    MAC_PATTERN,
    RENAME_KEY_MAP,
    RETRIES,
    TIMEOUT,
)
from .exceptions import ApiError, AuthFailed, CannotGetMac, InvalidSensorData
from .model import ConnectionOptions, NAMSensors

_LOGGER = logging.getLogger(__name__)


class NettigoAirMonitor:
    """Main class to perform Nettigo Air Monitor requests."""

    def __init__(self, session: ClientSession, options: ConnectionOptions) -> None:
        """Initialize."""
        self._session = session
        self.host = options.host
        self._options = options
        self._software_version: str

    @classmethod
    async def create(
        cls, session: ClientSession, options: ConnectionOptions
    ) -> NettigoAirMonitor:
        """Create a new device instance."""
        instance = cls(session, options)
        await instance.initialize()
        return instance

    async def initialize(self) -> None:
        """Initialize."""
        _LOGGER.debug("Initializing device %s", self.host)

        url = self._construct_url(ATTR_CONFIG, host=self.host)
        await self._async_http_request("get", url, retries=1)

    @staticmethod
    def _construct_url(arg: str, **kwargs: str) -> str:
        """Construct Nettigo Air Monitor URL."""
        return ENDPOINTS[arg].format(**kwargs)

    @staticmethod
    def _parse_sensor_data(data: dict[Any, Any]) -> dict[str, int | float]:
        """Parse sensor data dict."""
        result = {
            item["value_type"].lower(): round(float(item["value"]), 1) for item in data
        }

        for key, value in result.items():
            if "pressure" in key and value is not None:
                result[key] = round(value / 100)
            if (
                key
                in (
                    "conc_co2_ppm",
                    "sds_p1",
                    "sds_p2",
                    "sps30_p0",
                    "sps30_p1",
                    "sps30_p2",
                    "sps30_p4",
                    "signal",
                )
                and value is not None
            ):
                result[key] = round(value)

        for old_key, new_key in RENAME_KEY_MAP:
            if result.get(old_key) is not None:
                result[new_key] = result.pop(old_key)

        return result

    async def _async_http_request(
        self, method: str, url: str, retries: int = RETRIES
    ) -> Any:
        """Retrieve data from the device."""
        last_error = None
        for retry in range(retries):
            try:
                _LOGGER.debug("Requesting %s, method: %s", url, method)
                resp = await self._session.request(
                    method,
                    url,
                    raise_for_status=True,
                    timeout=TIMEOUT,
                    auth=self._options.auth,
                )
            except ClientResponseError as error:
                if error.status == HTTPStatus.UNAUTHORIZED.value:
                    raise AuthFailed("Authorization has failed") from error
                raise ApiError(
                    f"Invalid response from device {self.host}: {error.status}"
                ) from error
            except ClientConnectorError as error:
                _LOGGER.info(
                    "Invalid response from device: %s, retry: %s", self.host, retry
                )
                last_error = error
            else:
                _LOGGER.debug(
                    "Data retrieved from %s, status: %s", self.host, resp.status
                )
                if resp.status != HTTPStatus.OK.value:
                    raise ApiError(
                        f"Invalid response from device {self.host}: {resp.status}"
                    )

                return resp

            wait = TIMEOUT + retry
            _LOGGER.debug("Waiting %s seconds for device %s", wait, self.host)
            await asyncio.sleep(wait)

        raise ApiError(str(last_error))

    async def async_update(self) -> NAMSensors:
        """Retrieve data from the device."""
        url = self._construct_url(ATTR_DATA, host=self.host)

        resp = await self._async_http_request("get", url)
        data = await resp.json()

        self._software_version = data["software_version"]

        try:
            sensors = self._parse_sensor_data(data["sensordatavalues"])
        except (TypeError, KeyError) as error:
            raise InvalidSensorData("Invalid sensor data") from error

        if ATTR_UPTIME in data:
            sensors[ATTR_UPTIME] = int(data[ATTR_UPTIME])

        return from_dict(data_class=NAMSensors, data=sensors)

    async def async_get_mac_address(self) -> str:
        """Retrieve the device MAC address."""
        url = self._construct_url(ATTR_VALUES, host=self.host)
        resp = await self._async_http_request("get", url)
        data = await resp.text()

        if not (mac := re.search(MAC_PATTERN, data)):
            raise CannotGetMac("Cannot get MAC address from device")

        return cast(str, mac[0])

    @property
    def software_version(self) -> str:
        """Return software version."""
        return self._software_version

    async def async_restart(self) -> bool:
        """Restart the device."""
        url = self._construct_url(ATTR_RESTART, host=self.host)
        return await self._async_http_request("post", url, retries=1)

    async def async_ota_update(self) -> bool:
        """Trigger OTA update."""
        url = self._construct_url(ATTR_OTA, host=self.host)
        return await self._async_http_request("post", url, retries=1)
