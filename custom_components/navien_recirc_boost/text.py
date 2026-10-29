"""One editable row per day for the weekly schedule (device page > Configuration)."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DAY_NAMES
from .coordinator import NavienRecircConfigEntry, NavienRecircCoordinator
from .entity import NavienRecircEntity
from .schedule import (
    ScheduleError,
    build_day,
    day_windows,
    format_friendly,
    parse_windows,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienRecircConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one text row per day."""
    async_add_entities(DaySchedule(entry.runtime_data, num) for num in DAY_NAMES)


class DaySchedule(NavienRecircEntity, TextEntity):
    """A day's hot-water times, e.g. ``6am-8am, 5:30pm-9pm`` or ``off``."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_max = 120

    def __init__(self, coordinator: NavienRecircCoordinator, day: int) -> None:
        """Initialize."""
        super().__init__(coordinator, f"schedule_{DAY_NAMES[day]}")
        self._day = day

    @property
    def native_value(self) -> str | None:
        """The day's windows as the heater has them."""
        for day in self.coordinator.schedule or []:
            if day.get("day") == self._day:
                return format_friendly(day_windows(day))
        return None if not self.coordinator.schedule else "off"

    async def async_set_value(self, value: str) -> None:
        """Send the day's new windows to the heater."""
        try:
            windows = parse_windows(value)
        except ScheduleError as err:
            raise ServiceValidationError(f"{DAY_NAMES[self._day].title()}: {err}") from err
        if self.coordinator.boost.running:
            raise ServiceValidationError("A boost is running; change the schedule after it finishes")
        await self.coordinator.async_set_day(build_day(self._day, windows))
