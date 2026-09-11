"""Add Webasto ThermoConnect support to Home Assistant."""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, TypeAlias

from homeassistant.components.lovelace.const import (
    CONF_RESOURCE_TYPE_WS,
    LOVELACE_DATA,
    MODE_STORAGE,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_TYPE, CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration
from homeassistant.util import slugify as util_slugify
from pywebasto.enums import Request
from pywebasto.exceptions import InvalidRequestException, UnauthorizedException

try:
    from pywebasto.exceptions import (
        ForbiddenException,
        InvalidResponseException,
        TooManyRequestsException,
    )
except ImportError:
    ForbiddenException = InvalidRequestException
    InvalidResponseException = InvalidRequestException
    TooManyRequestsException = InvalidRequestException

from .api import WebastoConnectUpdateCoordinator
from .base import webasto_device_name
from .card_install import ensure_card_installed
from .const import CARD_FILENAME, CARD_WWW_SUBDIR, DOMAIN, PLATFORMS, STARTUP
from .services import async_register_services, async_unregister_services

LOGGER = logging.getLogger(__name__)
PENDING_APPROVAL_ISSUE_ID = "pending_approval"


@dataclass(slots=True)
class WebastoRuntimeData:
    """Runtime data for the Webasto config entry."""

    coordinator: WebastoConnectUpdateCoordinator
    update_listener: Callable[[], None]


WebastoConfigEntry: TypeAlias = ConfigEntry[WebastoRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: WebastoConfigEntry) -> bool:
    """Set up cloud API connector from a config entry."""
    coordinator = await _async_setup(hass, entry)
    async_register_services(hass)
    update_listener = entry.add_update_listener(async_reload_entry)
    entry.runtime_data = WebastoRuntimeData(
        coordinator=coordinator,
        update_listener=update_listener,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_migrate_unique_ids(
    hass: HomeAssistant,
    heater_id: int,
    heater_name: str,
    entry: ConfigEntry,
) -> None:
    """Migrate unique IDs to new format."""

    @callback
    def _async_migrator(entity_entry: er.RegistryEntry) -> dict[str, Any] | None:
        """Migrate an entity's unique ID."""
        updates = None
        entity_unique_id = entity_entry.unique_id
        entity_name = entity_entry.original_name

        if heater_name.lower() not in str(entity_entry.suggested_object_id):
            LOGGER.debug(
                "Skipping entity '%s' during migration, heater name '%s' not found in '%s'",
                entity_entry.entity_id,
                heater_name.lower(),
                entity_entry.suggested_object_id,
            )
            return None

        new_unique_id = util_slugify(f"{heater_id}_{entity_name}")

        if entity_unique_id == new_unique_id:
            LOGGER.debug(
                "No migration needed for entity '%s' with unique_id '%s'",
                entity_entry.entity_id,
                entity_unique_id,
            )
            return None

        LOGGER.debug(
            "Migrating entity '%s' unique_id from '%s' to '%s'",
            entity_entry.entity_id,
            entity_unique_id,
            new_unique_id,
        )
        updates = {"new_unique_id": new_unique_id}

        return updates

    await er.async_migrate_entries(
        hass,
        entry.entry_id,
        _async_migrator,
    )


async def _async_update_device_registry_name(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_id: int,
    device_name: str,
) -> None:
    """Update the device registry name."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get_device_by_identifier(
        (DOMAIN, str(device_id)), entry.entry_id
    )
    if device_entry is None or device_entry.name_by_user is not None:
        return
    if device_entry.name == device_name:
        return

    device_registry.async_update_device(device_entry.id, name=device_name)


# ... truncated for push - need full file
