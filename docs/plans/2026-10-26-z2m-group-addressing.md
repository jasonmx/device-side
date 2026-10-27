Z2M groups: address by group ID

Problem

Z2MTurnOnFor declares native_groups=True, but command_topic builds the topic from whatever follows zigbee2mqtt_ in the device identifier. For a group, Z2M writes zigbee2mqtt_<encoded base topic>_<group ID>, where the base topic is encoded as character codes joined with no separator (lib/extension/homeassistant.ts, getDevicePayload and getEncodedBaseTopic). So we publish to zigbee2mqtt/1221051039810110150109113116116_<ID>/set, Z2M resolves nothing, and the result still says sent. There is no is_group hook and no test or rig step for a Z2M group.

Verified in Z2M source (master)

- lib/zigbee.ts resolveEntity tr) first, thensettings.getGroup(key).
- lib/util/settings.ts getGroup -keyed groups map before it triesfriendly_name. So zigbee2mqtt/<ID>/set reaches the group and still works after a rename.
- Edge case: validateFriendlyNamws a purely numeric name, anddevices are looked up first. A device named exactly "<ID>" would therefore take the
  group's command. Document thisard against it.

Decisions (agreed)

- Address groups by ID: zigbee2m_time into one OnWithTimedOff that reaches every member at once.
- If a group's encoded base topie the group as not_addressablerather than send to a dead topic. Devices keep assuming the default base topic, because
  their identifiers don't carry

Changes

1. integrations/zigbee2mqtt/addr
   - Encode the default base topic the way Z2M does: "".join(str(ord(c)) for c in
     "zigbee2mqtt"). Don't hardc
   - Parse the address: ^(\d+)_(\d+)$ is a group (encoded base topic, then ID). IEEE
     addresses start with 0x, so
   - Add is_z2m_group(hass, target) -> bool, true for any address with the group shape,
     whatever its base topic. Th base topic is recognized as agroup and then refused.
   - command_topic:
     - device → zigbee2mqtt/<ieee>/set (unchanged)
     - group on the default baseset
     - group on any other base topic → None, which supports() already turns into
       not_addressable
2. integrations/zigbee2mqtt/__init__.py: set is_group=is_z2m_group.
3. integrations/zigbee2mqtt/turntive_groups comment to say groupentities receive commands on <base>/<group ID>/set. Change only the comment, so the AST
   fingerprint stays the same. Ttal=True.
4. Tests (tests/fixtures/z2m.py, tests/integrations/zigbee2mqtt/test_turn_on_for.py)
   - Add a fixture add_z2m_grouproup_id, base_topic="zigbee2mqtt") that writes the identifier the way Z2M does.
   - Pin the encoding to the lit09113116116", so the test checksZ2M's scheme rather than our own function.
   - Group without fields: one p/set with{"state":"ON","on_time":…}, result sent.
   - Group with fields: light.tu then the publish.
   - Group on a custom base topic: unsupported / not_addressable, and nothing published.
   - is_z2m_group is true for a ce.
   - A device and a group in one call each get their own topic.
5. docs/integrations.md, Zigbee2
   - "How targets resolve": add the group identifier's shape and its topic, citing getGroup.
   - Rewrite "Groups": a group i the group's ID topic, and getsone simultaneous OnWithTimedOff.
   - Sharp edges: a custom base s but still misfires for devices;a device whose friendly name is the group's ID takes the group's command.
   - Check the README feature tanst this (memory:readme-describes-next-release).
6. Rig engine (tests/rig/engine.): the engine reads a group'smembers from its entity_id attribute, which Z2M's MQTT group light doesn't have. Without
   a fix, the rig neither watche. Add an optional members: list on a group's inventory entry, and use it when the attribute is missing. Cover it with a
   unit test, and document it inle.yaml.

Rig verification (after merge)

- Hardware (Jason): two CT bulbsin one Z2M group that HA exposesas a light. One of the two also serves as the single bulb. Plugs won't do: a Z2M plug
  group shows up in HA as switchpter's light scope. Plugs alsorarely honor OnWithTimedOff (memory: zigbee-plugs-unsupported).
- Inventory: add a zigbee2mqtt lingle bulb and group on the groupentity, with members: listing the two bulbs.
- Run: a watched session, briefeon's go, running scripts/rig.py--integration zigbee2mqtt. A full pass writes docs/bench/zigbee2mqtt/turn_on_for.md. The adapter keeps its experimentalhe record counts toward beta oncethe flag is lifted.
