"""Hue set_scene: the scene replayed as light PUTs that turn nothing on, ported from hue_dimmer's tests."""

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.device_side.integrations.hue.transition_cache import transition_cache

from ...conftest import call, refusal
from ...fixtures.hue import add_hue_entity, hue_entry, light_action

pytestmark = pytest.mark.usefixtures("setup_production")

SENT = {"status": "sent", "integration": "hue"}


async def scene(hass, bridge, *actions, smart: bool = False, lights=("light-1",)) -> str:
    for light_id in lights:
        bridge.light(light_id)
    bridge.scene("scene-1", list(actions), smart=smart)
    entry = await hue_entry(hass, bridge)
    return add_hue_entity(hass, entry, "scene.relax", "scene-1")


@pytest.mark.parametrize(
    ("action", "put"),
    [
        pytest.param(
            {"dimming": {"brightness": 60.0}, "color_temperature": {"mirek": 366}},
            {"dimming": {"brightness": 60.0}, "color_temperature": {"mirek": 366}},
            id="ct",
        ),
        pytest.param(
            {"dimming": {"brightness": 40.0}, "color": {"xy": {"x": 0.5, "y": 0.4}}},
            {"dimming": {"brightness": 40.0}, "color": {"xy": {"x": 0.5, "y": 0.4}}},
            id="xy",
        ),
        pytest.param({"dimming": {"brightness": 25.0}}, {"dimming": {"brightness": 25.0}}, id="brightness_only"),
        pytest.param(
            {"on": {"on": True}, "dimming": {"brightness": 80.0}}, {"dimming": {"brightness": 80.0}}, id="on_dropped"
        ),
        pytest.param(
            {"on": {"on": False}, "dimming": {"brightness": 30.0}, "color_temperature": {"mirek": 400}},
            {"on": {"on": False}, "dimming": {"brightness": 30.0}, "color_temperature": {"mirek": 400}},
            id="off_sent_with_settings",
        ),
        pytest.param(
            {"dimming": {"brightness": 70.0}, "color": {"xy": {"x": 0.4, "y": 0.4}}, "color_temperature": {}},
            {"dimming": {"brightness": 70.0}, "color": {"xy": {"x": 0.4, "y": 0.4}}},
            id="mirek_none_not_sent",
        ),
    ],
)
async def test_single_light(hass, bridge, action, put):
    await scene(hass, bridge, light_action("light-1", **action))

    response = await call(hass, "set_scene", {"entity_id": "scene.relax"})
    # A scene has no light fields, so nothing is dropped and the result carries no detail.
    assert response == {"scene.relax": SENT}
    assert bridge.puts == [("light/light-1", put)]


async def test_every_light_of_the_scene_is_written(hass, bridge):
    await scene(
        hass,
        bridge,
        light_action("light-1", dimming={"brightness": 20.0}, color_temperature={"mirek": 450}),
        light_action("light-2", dimming={"brightness": 90.0}, color={"xy": {"x": 0.6, "y": 0.3}}),
        lights=("light-1", "light-2"),
    )

    await call(hass, "set_scene", {"entity_id": "scene.relax"})

    assert bridge.puts == [
        ("light/light-1", {"dimming": {"brightness": 20.0}, "color_temperature": {"mirek": 450}}),
        ("light/light-2", {"dimming": {"brightness": 90.0}, "color": {"xy": {"x": 0.6, "y": 0.3}}}),
    ]


@pytest.mark.parametrize(
    "action",
    [
        pytest.param(light_action("light-1", on={"on": True}), id="nothing_to_write"),
        pytest.param(light_action("light-1", color_temperature={}), id="only_null_mirek"),
        pytest.param(light_action("grouped-1", "grouped_light", dimming={"brightness": 50.0}), id="not_a_light"),
    ],
)
async def test_actions_with_nothing_to_write_are_skipped(hass, bridge, action):
    await scene(hass, bridge, action)

    response = await call(hass, "set_scene", {"entity_id": "scene.relax"})

    assert response == {"scene.relax": {"status": "unchanged", "integration": "hue", "detail": "nothing_to_set"}}
    assert bridge.puts == []


async def test_smart_scene_is_refused(hass, bridge):
    # smart_scene is unsupported: a named target raises before anything is sent.
    bridge.light("light-1")
    bridge.scene("scene-1", [], smart=True)
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "scene.relax", "scene-1")

    assert await refusal(hass, "set_scene", {"entity_id": "scene.relax"}) == "smart_scene"
    assert bridge.puts == []


async def test_missing_scene_is_rejected(hass, bridge):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "scene.relax", "scene-1")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "set_scene", {"entity_id": "scene.relax"})

    assert raised.value.translation_placeholders["summary"] == "scene.relax: scene_not_found"
    assert bridge.puts == []


async def test_light_target_is_outside_the_action(hass, bridge):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.lamp", "light-1")

    assert await refusal(hass, "set_scene", {"entity_id": "light.lamp"}) == "domain_not_supported"


async def test_one_failing_light_does_not_stop_the_others(hass, bridge, caplog):
    await scene(
        hass,
        bridge,
        *(light_action(f"light-{n}", dimming={"brightness": 20.0 * n}) for n in (1, 2, 3)),
        lights=("light-1", "light-2", "light-3"),
    )
    bridge.failing.add("light-2")

    response = await call(hass, "set_scene", {"entity_id": "scene.relax"})

    assert response == {"scene.relax": SENT | {"detail": "some_lights_failed"}}
    assert [path for path, _ in bridge.puts] == ["light/light-1", "light/light-2", "light/light-3"]
    assert "light-2" in caplog.text


async def test_every_light_failing_rejects(hass, bridge):
    await scene(hass, bridge, light_action("light-1", dimming={"brightness": 20.0}))
    bridge.failing.add("light-1")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "set_scene", {"entity_id": "scene.relax"})

    assert raised.value.translation_placeholders["summary"] == "scene.relax: error"


async def test_scene_is_reread_on_each_call(hass, bridge):
    await scene(hass, bridge, light_action("light-1", dimming={"brightness": 20.0}))
    await call(hass, "set_scene", {"entity_id": "scene.relax"})

    # An edit in the Hue app reaches aiohue's cache as an event; this is the model it leaves behind.
    bridge.api.scenes.scene["scene-1"].actions[0].action.dimming.brightness = 75.0
    await call(hass, "set_scene", {"entity_id": "scene.relax"})

    assert bridge.puts[-1] == ("light/light-1", {"dimming": {"brightness": 75.0}})


async def test_v1_bridge_is_refused(hass, bridge):
    bridge.scene("scene-1", [])
    entry = await hue_entry(hass, bridge, api_version=1)
    add_hue_entity(hass, entry, "scene.relax", "scene-1")

    assert await refusal(hass, "set_scene", {"entity_id": "scene.relax"}) == "bridge_v1"


async def test_the_lights_written_forget_their_move_predictions(hass, bridge):
    await scene(
        hass,
        bridge,
        light_action("light-1", dimming={"brightness": 20.0}),
        light_action("light-2", dimming={"brightness": 90.0}),
        lights=("light-1", "light-2"),
    )
    cache = transition_cache(hass)
    for light_id in ("light-1", "light-2"):
        cache.stopped(light_id, "brightness", 42.0)
    bridge.failing.add("light-2")

    await call(hass, "set_scene", {"entity_id": "scene.relax"})

    assert not cache.follows("light-1")
    assert cache.follows("light-2")  # its write failed, so the light is still where the move left it
