from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.navien_recirc_boost.const import DOMAIN

DATA = {"username": "a@b.c", "password": "pw", "device_index": 0}
OPTS = {"stop_offset": 5, "extra_minutes": 2, "max_minutes": 15}


async def _setup(hass):
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options=OPTS, unique_id="a1b2c3d4e5f6")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_config_flow(hass: HomeAssistant, fake_client):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], {"username": "a@b.c", "password": "bad"})
    assert bad["errors"] == {"base": "invalid_auth"}
    with patch("custom_components.navien_recirc_boost.async_setup_entry", return_value=True), \
         patch("custom_components.navien_recirc_boost.async_unload_entry", return_value=True):
        ok = await hass.config_entries.flow.async_configure(result["flow_id"], {"username": "a@b.c", "password": "pw"})
        await hass.async_block_till_done(wait_background_tasks=True)
        assert ok["type"] is FlowResultType.CREATE_ENTRY
        assert await hass.config_entries.async_unload(ok["result"].entry_id)
    assert ok["result"].unique_id == "a1b2c3d4e5f6"
    assert ok["options"]["stop_offset"] == 5


async def test_setup_entities(hass: HomeAssistant, fake_client):
    entry = await _setup(hass)
    states = {s.entity_id: s for s in hass.states.async_all() if s.entity_id.split(".")[1].startswith("npe2")}
    names = sorted(states)
    print(names)
    sched = next(s for e, s in states.items() if e.startswith("sensor.") and e.endswith("_schedule"))
    assert sched.state == "on"
    assert sched.attributes["monday"] == "04:00-08:00, 15:30-21:00"
    assert hass.states.get("switch.npe2_recirc_boost_weekly_schedule").state == "on"
    assert hass.states.get("number.npe2_recirc_boost_target_temperature").state in ("130", "130.0")
    assert hass.states.get("sensor.npe2_recirc_boost_boosts_total").state == "0"
    assert hass.states.get("binary_sensor.npe2_recirc_boost_boost_running").state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_boost_reaches_temp_and_restores(hass: HomeAssistant, fake_client, fast_boost):
    entry = await _setup(hass)
    client = fake_client.instances[-1]
    client.inlet_rise = 10  # 90 -> 100 -> ... -> 130 reaches 125
    await hass.services.async_call("button", "press", {"entity_id": "button.npe2_recirc_boost_boost"}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    coord = entry.runtime_data
    assert not coord.boost.running
    assert coord.boost.result == "reached temperature"
    assert coord.boost.stop_temp == 125
    assert [w[0] for w in client.writes] == [False, True]
    assert client.writes[0][1] == client.writes[1][1]  # same live schedule put back
    assert len(client.writes[1][1]) == 7
    assert client.channels[1].status["weeklyControl"] == 1
    assert hass.states.get("sensor.npe2_recirc_boost_boosts_today").state == "1"
    assert hass.states.get("sensor.npe2_recirc_boost_boosts_total").state == "1"
    assert hass.states.get("sensor.npe2_recirc_boost_last_boost").state not in ("unknown", "unavailable")
    assert coord.saved["boost_in_progress"] is False


async def test_boost_cap_and_retry(hass: HomeAssistant, fake_client, fast_boost):
    entry = await _setup(hass)
    client = fake_client.instances[-1]
    client.inlet_rise = 0
    with patch("custom_components.navien_recirc_boost.boost.BOOST_CHECK_SECONDS", 60):
        entry.runtime_data.boost.async_start(max_minutes=0.05)  # 3 s cap -> one check
        await hass.async_block_till_done(wait_background_tasks=True)
    coord = entry.runtime_data
    assert coord.boost.result == "hit safety cap"
    assert client.writes[-1][0] is True


async def test_restore_failure_notifies(hass: HomeAssistant, fake_client, fast_boost):
    entry = await _setup(hass)
    client = fake_client.instances[-1]
    coord = entry.runtime_data
    client.fail_writes = 4
    ok = await coord.boost.async_restore(client.schedule, True)
    assert ok is False
    notes = hass.states.async_all("persistent_notification")
    # persistent notifications are no longer states in new HA; check the store instead
    from homeassistant.components import persistent_notification as pn
    assert any("could not turn" in n["message"] for n in pn._async_get_or_create_notifications(hass).values())


async def test_recover_after_restart(hass: HomeAssistant, fake_client, fast_boost, hass_storage):
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options=OPTS, unique_id="a1b2c3d4e5f6")
    entry.add_to_hass(hass)
    from .conftest import SCHEDULE
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1, "minor_version": 1, "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"boost_in_progress": True, "boost_schedule": SCHEDULE, "boost_restore_enabled": True,
                 "boosts_total": 7},
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    client = fake_client.instances[-1]
    assert client.writes and client.writes[0][0] is True
    assert entry.runtime_data.saved["boost_in_progress"] is False
    assert hass.states.get("sensor.npe2_recirc_boost_boosts_total").state == "7"


async def test_options_flow_settings_and_edit_day(hass: HomeAssistant, fake_client):
    entry = await _setup(hass)
    client = fake_client.instances[-1]
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU
    r2 = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "boost_settings"})
    r3 = await hass.config_entries.options.async_configure(r2["flow_id"], {"stop_offset": 3, "extra_minutes": 1, "max_minutes": 10})
    assert r3["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["stop_offset"] == 3

    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "schedule"})
    assert r["step_id"] == "schedule"
    week = {"enabled": True, "sunday": "07:00-09:00, 14:00-21:00", "monday": "04:00-08:00, 15:30-21:00",
            "tuesday": "04:00-08:00, 15:30-21:00", "wednesday": "04:00-08:00, 15:30-21:00",
            "thursday": "04:00-08:00, 15:30-21:00", "friday": "04:00-08:00, 15:30-22:00", "saturday": "07:00-22:00"}
    defaults = {str(k.schema): k.default() for k in r["data_schema"].schema}
    assert defaults == week
    writes_before = len(client.writes)
    bad = await hass.config_entries.options.async_configure(r["flow_id"], {**week, "monday": "nonsense"})
    assert bad["errors"] == {"monday": "bad_windows"}
    assert len(client.writes) == writes_before
    done = await hass.config_entries.options.async_configure(
        r["flow_id"], {**week, "saturday": "06:00-11:00, 16:00-21:30", "sunday": "off"})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    enabled, sent = client.writes[-1]
    assert enabled is True and [d["day"] for d in sent] == [1, 7]
    assert sent[1]["schdList"][-1] == {"num": 4, "hh": 21, "mm": 30, "flag": 2}
    attrs = hass.states.get("sensor.npe2_recirc_boost_schedule").attributes
    assert attrs["saturday"] == "06:00-11:00, 16:00-21:30" and attrs["sunday"] == "off"

    # Nothing changed except turning the schedule off: the whole week goes back with "off".
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "schedule"})
    cur = {str(k.schema): k.default() for k in r["data_schema"].schema}
    done = await hass.config_entries.options.async_configure(r["flow_id"], {**cur, "enabled": False})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert client.writes[-1][0] is False and len(client.writes[-1][1]) == 7


async def test_services_and_switch_and_number(hass: HomeAssistant, fake_client):
    await _setup(hass)
    client = fake_client.instances[-1]
    await hass.services.async_call(DOMAIN, "set_day_schedule", {"day": "sunday", "windows": "off"}, blocking=True)
    assert client.writes[-1][1] == [{"day": 1, "schdCnt": 0, "schdList": []}]
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.npe2_recirc_boost_weekly_schedule"}, blocking=True)
    assert client.writes[-1][0] is False and len(client.writes[-1][1]) == 7
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("switch.npe2_recirc_boost_weekly_schedule").state == "off"
    await hass.services.async_call("number", "set_value", {"entity_id": "number.npe2_recirc_boost_target_temperature", "value": 125}, blocking=True)
    assert client.channels[1].temps == [125]


async def test_week_service_and_boost_setting_numbers(hass: HomeAssistant, fake_client):
    entry = await _setup(hass)
    client = fake_client.instances[-1]
    await hass.services.async_call(
        DOMAIN, "set_week_schedule",
        {"tuesday": "06:00-08:00, 17:00-23:59", "thursday": "off"}, blocking=True,
    )
    enabled, days = client.writes[-1]
    assert enabled is True
    assert [d["day"] for d in days] == [3, 5]
    assert days[0]["schdCnt"] == 4 and days[1]["schdCnt"] == 0
    import pytest
    from homeassistant.exceptions import ServiceValidationError
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "set_week_schedule", {"monday": "09:00-08:00"}, blocking=True)

    offset = "number.npe2_recirc_boost_boost_1_stop_this_close_to_target"
    assert hass.states.get(offset).state in ("5", "5.0")
    await hass.services.async_call("number", "set_value", {"entity_id": offset, "value": 8}, blocking=True)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.npe2_recirc_boost_boost_3_never_run_longer_than", "value": 20}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.options["stop_offset"] == 8 and entry.options["max_minutes"] == 20
    assert hass.states.get(offset).state in ("8", "8.0")
    assert hass.states.get("number.npe2_recirc_boost_boost_2_extra_run_once_hot").state in ("2", "2.0")


async def test_day_text_rows(hass: HomeAssistant, fake_client):
    import pytest
    from homeassistant.exceptions import ServiceValidationError
    await _setup(hass)
    client = fake_client.instances[-1]
    mon = "text.npe2_recirc_boost_schedule_2_monday"
    assert hass.states.get(mon).state == "4am-8am, 3:30pm-9pm"
    await hass.services.async_call("text", "set_value", {"entity_id": mon, "value": "6-8am, 5:30pm-12am"}, blocking=True)
    assert client.writes[-1][1] == [{"day": 2, "schdCnt": 4, "schdList": [
        {"num": 1, "hh": 6, "mm": 0, "flag": 1}, {"num": 2, "hh": 8, "mm": 0, "flag": 2},
        {"num": 3, "hh": 17, "mm": 30, "flag": 1}, {"num": 4, "hh": 23, "mm": 59, "flag": 2}]}]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("text", "set_value", {"entity_id": mon, "value": "9am-8am"}, blocking=True)
