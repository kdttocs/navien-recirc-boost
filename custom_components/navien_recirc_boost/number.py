"""Heater target temperature and the boost settings."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EXTRA_MINUTES,
    CONF_MAX_MINUTES,
    CONF_STOP_OFFSET,
    DEFAULT_EXTRA_MINUTES,
    DEFAULT_MAX_MINUTES,
    DEFAULT_STOP_OFFSET,
)
from .coordinator import NavienRecircConfigEntry, NavienRecircCoordinator
from .entity import NavienRecircEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienRecircConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the numbers."""
    coord = entry.runtime_data
    async_add_entities(
        [
            TargetTemperature(coord, "target_temperature"),
            BoostSetting(coord, CONF_STOP_OFFSET, DEFAULT_STOP_OFFSET, 1, 20, None),
            BoostSetting(coord, CONF_EXTRA_MINUTES, DEFAULT_EXTRA_MINUTES, 0, 15, UnitOfTime.MINUTES),
            BoostSetting(coord, CONF_MAX_MINUTES, DEFAULT_MAX_MINUTES, 1, 60, UnitOfTime.MINUTES),
        ]
    )


class TargetTemperature(NavienRecircEntity, NumberEntity):
    """The temperature the heater heats water to."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = NumberMode.BOX

    @property
    def native_unit_of_measurement(self) -> str:
        """Follow the heater's own unit setting."""
        if self.coordinator.is_fahrenheit:
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def native_step(self) -> float:
        """Whole degrees in Fahrenheit, half degrees in Celsius."""
        return 1 if self.coordinator.is_fahrenheit else 0.5

    @property
    def native_min_value(self) -> float:
        """Lowest the heater allows."""
        return float(self.coordinator.info.get("setupDHWTempMin") or (97 if self.coordinator.is_fahrenheit else 36))

    @property
    def native_max_value(self) -> float:
        """Highest the heater allows."""
        return float(self.coordinator.info.get("setupDHWTempMax") or (140 if self.coordinator.is_fahrenheit else 60))

    @property
    def native_value(self) -> float | None:
        """Current target."""
        return self.coordinator.target_temp

    async def async_set_native_value(self, value: float) -> None:
        """Set a new target."""
        await self.coordinator.async_set_target(value)


class BoostSetting(NavienRecircEntity, NumberEntity):
    """A boost setting, shown under Configuration on the device page.

    Stored in the integration's options, so it is the same value the
    Configure > Boost settings form shows.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: NavienRecircCoordinator,
        key: str,
        default: int,
        minimum: int,
        maximum: int,
        unit: str | None,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, key)
        self._key = key
        self._default = default
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_unit_of_measurement = unit

    @property
    def available(self) -> bool:
        """A setting, so always available."""
        return True

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Degrees follow the heater's unit."""
        if self._key == CONF_STOP_OFFSET:
            return UnitOfTemperature.FAHRENHEIT if self.coordinator.is_fahrenheit else UnitOfTemperature.CELSIUS
        return self._attr_native_unit_of_measurement

    @property
    def native_value(self) -> float:
        """Current setting."""
        return float(self.coordinator.config_entry.options.get(self._key, self._default))

    async def async_set_native_value(self, value: float) -> None:
        """Save the new setting (used from the next boost on)."""
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, self._key: int(value)}
        )
