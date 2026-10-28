"""The schedule messages match what the NaviLink app sent (captured Oct 28, 2026)."""

import json
import pathlib

from custom_components.navien_recirc_boost.navilink import protocol
from custom_components.navien_recirc_boost.navilink.client import NavilinkClient

T = protocol.Topics(device_type=2, mac="a1b2c3d4e5f6", home_seq="11111", user_seq="22222", client_id="CID")


def test_read_msg_matches_app():
    msg = protocol.weekly_read_msg(T, "0000", 1)
    assert msg["requestTopic"] == "cmd/2/navilink-a1b2c3d4e5f6/status/weeklyschedule"
    assert msg["responseTopic"] == "cmd/2/11111/22222/CID/res/weeklyschedule"
    assert msg["request"] == {"additionalValue": "0000", "command": 16777222, "deviceType": 2,
                              "macAddress": "a1b2c3d4e5f6", "status": {"channelNumber": 1}}
    assert T.weekly_res in T.subscriptions


def test_write_msg_matches_app():
    day = {"schdList": [{"hh": 8, "num": 1, "flag": 1, "mm": 0}], "day": 1, "schdCnt": 1}
    msg = protocol.weekly_write_msg(T, "0000", 1, True, [day])
    assert msg["requestTopic"] == "cmd/2/navilink-a1b2c3d4e5f6/control/weeklyschedule"
    assert msg["request"]["command"] == 33554438
    assert msg["request"]["control"] == {"channelNumber": 1, "weeklyControl": 1, "weeklyScheduleList": [day]}
    assert protocol.weekly_write_msg(T, "0000", 1, False, [])["request"]["control"]["weeklyControl"] == 2


def test_client_parses_reply():
    reply = json.loads((pathlib.Path(__file__).parent / "sample_sched_response.json").read_text())
    client = NavilinkClient("u", "p", session=None)
    client._handle_message("x/res/weeklyschedule", {"response": {"weeklySchedule": reply}})
    got = client.weekly[1]
    assert got["weekly_control"] == 1
    assert len(got["schedule"]) == 7 and got["schedule"][6]["schdCnt"] == 2
