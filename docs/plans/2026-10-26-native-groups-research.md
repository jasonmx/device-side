# Native groups survey (slice 9e): research

Research half of slice 9e: for each integration beyond Hue, whether HA exposes an integration-native group,
how device_side would detect and address it, and whether one group command keeps `turn_on_for`'s
device-side timer on every member. No decisions here; they come from the 9e plan interview, and the rig
checks below come after it.

Sources were read at: Z2M `344b6e0`, zigbee-herdsman `6764136`, zigbee-herdsman-converters `7462b54`; HA core,
zigpy and zigpy/zha at `dev` on 2026-10-26; the Zigbee Cluster Library spec, revision 7 (ZCL below).

## Summary

| Integration | Group entity in HA | One group command for `turn_on_for` | Members readable (`expand_group` possible) | Today |
|---|---|---|---|---|
| Zigbee2MQTT | yes: light, switch, lock, cover | yes, a ZCL groupcast `OnWithTimedOff` | yes, retained `zigbee2mqtt/bridge/groups` | **fixed since (#59, rig-tested in #62):** at the time of writing, `native_groups=True`, but a group got a topic that reached nothing and the result said `sent` |
| ZHA | yes: light, switch, fan | yes, `zha.issue_zigbee_group_command` (groupcast) | yes, ZHA gateway's group members | groups flagged, no hook: `unsupported` (`group_not_supported`) |
| Matter | no | no API in HA's stack | n/a | nothing to do |
| Shelly | no | no cross-device groups on the LAN | n/a | nothing to do |

## What every Zigbee groupcast shares

These hold for Z2M and ZHA alike, because both end in the same ZCL frame sent to a group address.

- **Each member runs its own timer.** `OnWithTimedOff` sets the member's own `OnTime`, which it counts down
  every 0.1 s and then turns off (ZCL §3.8.2.3.6.4). Nothing about the timer lives on the coordinator.
- **A shorter timer can't shorten a running one.** On receipt the device sets `OnTime` to the *maximum* of the
  running value and the new one (ZCL §3.8.2.3.6.4). This holds per device too, but in a group, members whose
  timers were started at different times end at different times.
- **No delivery feedback.** Groupcast has no APS ack, and a device sends no Default Response to a command it
  didn't receive by unicast (ZCL §2.5.12.2, criterion 1). zigpy's `Group.request` returns a synthesized
  SUCCESS at once (`zigpy/group.py`); Z2M's z-stack adapter returns after a 200 ms settle wait ("a group
  command is not confirmed and thus immediately returns", `zStackAdapter.ts:740-765`). So a group result can
  only ever be `sent`.
- **A member that can't run the timer fails silently.** A member that doesn't support the command discards a
  multicast without a Default Response (ZCL §2.5.12.2). By unicast the same device answers
  `UNSUP_CLUSTER_COMMAND`, which device_side can report as `rejected`. Per the ZCL, "discarded" means that
  member doesn't turn on at all. **Unverified:** how real firmware handles it.
- **Sleeping end devices miss groupcasts** (ZCL §3.6: groupcasts go to `macRxOnWhenIdle` devices only).
  Mains-powered lights aren't sleepy, so this doesn't matter for lights.
- **Groupcast can fail as a whole.** Z2M #32885 (open): after a coordinator swap (CC2652P to CC2674P10), every
  groupcast fails with `NWK_NO_ROUTE` while unicast works. device_side's Z2M path publishes to MQTT and
  never sees Z2M's errors, so it would still report `sent`.

Trade-off against expanding the group (`expand_group`, one unicast per member): expansion keeps per-member
`rejected` and, on ZHA, `confirmed`, and gets the stack's unicast retries, at the cost of N commands through
the integration semaphore (ZHA 2, Z2M 4), so members start a little apart.

## Zigbee2MQTT

### Exposure and detection

- Z2M gives a group the HA device identifier `zigbee2mqtt_<encoded base topic>_<group ID>`, where the base
  topic is encoded as concatenated decimal character codes: `zigbee2mqtt` becomes
  `1221051039810110150109113116116`. A device gets `zigbee2mqtt_<ieee>` (`getDevicePayload`,
  `lib/extension/homeassistant.ts:2161-2171`; `getEncodedBaseTopic`).
- Group entities exist for `light`, `switch`, `lock` and `cover` (`GROUP_SUPPORTED_TYPES`,
  `homeassistant.ts:47`). unique_id is `<group ID>_<object_id>_<base topic>` (`homeassistant.ts:1833`).
- The discovered `command_topic` is `<base topic>/<group friendly_name>/set` (`homeassistant.ts:1787,
  1896-1900`).

### The bug in the current adapter

`detect.py` matches any identifier starting `zigbee2mqtt_`, so a group is detected. `addressing.py` strips
that prefix and keeps the rest as the address, so a group gets
`zigbee2mqtt/1221051039810110150109113116116_<ID>/set`. Z2M's `resolveEntity` (`lib/zigbee.ts:322`) looks
groups up by ID or friendly_name only, so the publish reaches nothing, and the adapter returns `sent`.
`IntegrationInfo` for Z2M has no `is_group`, so the resolver never flags a group and the dispatcher's group
logic never runs. No unit test or rig step covers a Z2M group.

Ways to address a group correctly, for the plan to choose between:

- the last `_` segment of the identifier is the numeric group ID, and Z2M accepts `zigbee2mqtt/<ID>/set`
  (`settings.getGroup` matches by ID);
- the entity's discovered `command_topic`, which the repo plan's Z2M route already names as the first choice;
- decoding the base topic from the identifier would also fix the custom-base-topic sharp edge, for groups
  only.

### Group command path

- For a group, `publish.ts` takes the **union** of every member definition's `toZigbee` converters
  (`getDefinitionConverters`).
- `{"state":"ON","on_time":X}` reaches zigbee-herdsman-converters' `on_off` converter (`toZigbee.ts:16-56`),
  which calls `entity.command("genOnOff", "onWithTimedOff", {ctrlbits: 0, ontime: round(X*10), offwaittime})`.
  `off_wait_time` is accepted and defaults to 0. On a group entity that is `Group.command` then
  `sendZclFrameToGroup`: one groupcast, not one command per member.
- Evidence it works on hardware: Z2M #29158, a user report that an IKEA LED2005R5 ignores `on_time` by unicast
  but honors it when sent to a group. One device model, no fix in code.

### State in HA

- The `on_time` branch of `on_off` returns nothing, so Z2M publishes no optimistic state for the command,
  either for the group or its members (`publish.ts:210-230`).
- Members' own reports do reach the group: `groups.ts` `onStateChange` copies a member's state change to every
  optimistic group it belongs to (`optimistic` is on by default), and with the default
  `off_state: all_members_off` the group shows off only once every member is off (`shouldPublishPayloadForGroup`).
  So the group entity tracks the timer as well as the members' reporting does. (The Z2M researcher concluded
  the group stays stale; the `groups.ts` code says otherwise.)
- Z2M #32891 (open PR) would add a separate `group_state` with `PARTIAL`; `state` is unchanged.

### With fields

The adapter's `light.turn_on` on a group entity goes to the group topic, and Z2M sends level/color as
groupcasts using the union of converters. Then the `on_time` publish follows. A member without level control
gets a level command it can't run (a general Z2M group limitation, not specific to timers).

### Members

Z2M publishes `zigbee2mqtt/bridge/groups`, retained, with
`[{id, friendly_name, members: [{ieee_address, endpoint}]}]`, on startup and on every membership change
(`lib/extension/bridge.ts:892-911`). An `expand_group` hook could read it through HA's `mqtt` integration and
map `ieee_address` back to entities by the `zigbee2mqtt_<ieee>` identifier.

## ZHA

### Exposure and detection

- Group entities exist for `light`, `switch` and `fan` (`GROUP_ENTITY_DOMAINS`, HA core `zha/helpers.py`).
- unique_id is `{platform}_zha_group_0x{group_id:04x}` (zha library, `GroupEntity.__init__`), already matched
  by `addressing.py`'s `_GROUP_MARKER`. The group ID parses from the hex after `_zha_group_0x`.
- A group has no device of its own: its entities hang off the coordinator device (HA core `zha/helpers.py`,
  `_create_entity_metadata`). So the device registry can't tell one group from another, only the unique_id can.

### Group command path

- `zha.issue_zigbee_group_command` (HA core `zha/services.py`): `group`, `cluster_id`, `command`, optional
  `cluster_type`, `manufacturer`, and `args`, a **positional list only**. Unlike the cluster command, it has no
  `params`. So `OnWithTimedOff` is `cluster_id: 6, command: 0x42, args: [0, on_time_tenths, 0]` (field order:
  on/off control, on time, off wait time).
- It looks the group up with `gateway.get_group(group_id)`; **when the group doesn't exist it does nothing and
  raises nothing** (`_issue_zigbee_group_command`). An adapter would have to check the group itself first.
- The command goes `group.endpoint[cluster].command(...)`, then zigpy `Group.request` with
  `AddrMode.Group`: a real groupcast, with the synthesized SUCCESS described above.
- It is registered with `async_register_admin_service`, which checks `call.context.user_id` on every call and
  raises `Unauthorized` for a non-admin user (HA core `helpers/service.py:1018-1023`). So the adapter must pass
  the caller's `context`, as the per-device path already does. (The ZHA researcher said the service takes no
  context; the helper shows the check is made on the context of each call.)
- No attribute read exists for a group address, so `OnTime` read-back (today's `confirmed`) is impossible.

### State in HA

The zha library's `LightGroup` derives its state from members: on if any available member is on
(`zha/application/platforms/light/__init__.py`). Members change state when they report. HA #106360 (closed,
stale) reports a ZHA group light not updating after `issue_zigbee_group_command`. How long members take to
report after a timed off is **unverified**; the rig will show it.

### With fields

`light.turn_on` on a ZHA light group sends groupcast `move_to_level_with_on_off` on the group's Level Control
endpoint, and color through its Color Control endpoint; enhanced light transition is off for groups
(`LightGroup`, zha library). The two-step order (fields, then the timer) works as it does per device.

### Members

`get_zha_gateway(hass).get_group(group_id).members`, each a `GroupMember` with `.device.ieee` and
`.endpoint_id` (zha library `zha/zigbee/group.py`). `zcl.py` already uses `get_zha_gateway`, so an
`expand_group` hook adds no new kind of dependency. Member targets would then go through today's per-device
path, with confirmation.

## Matter

No native group to support:

- HA's `matter` integration creates entities per endpoint only; nothing in `discovery.py` produces a group or
  aggregator entity. A Matter bridge's devices each become their own entity.
- HA now requires `matter-python-client==1.5.5` (manifest) against the matter.js-based server;
  python-matter-server was archived on 2026-06-23. Neither server offers a group command:
  `send_device_command` and `send_batched_device_commands` address one node.
- The Matter spec does define groupcast (with controller-provisioned group keys); **unverified** whether
  `OnWithTimedOff` is permitted by groupcast, and moot until HA's stack exposes one.

## Shelly

No native group to support:

- HA's `shelly` integration makes one entity per RPC component (unique_id `{mac}-{key}`), so a two-channel
  device is two entities; nothing aggregates (`shelly/entity.py`, `switch.py`, `light.py`).
- Gen2+ `Switch.SetAll`/`SetMany` and `Light.SetAll`/`SetMany` act on outputs of one device only (Shelly Gen2
  API docs, Switch component). Shelly's Groups feature is cloud-only. Gen1 CoIoT groups don't matter:
  Gen1 is unsupported.

## Open questions for the 9e plan interview

1. **Z2M:** fix the group address and prove the groupcast, or turn `native_groups` off and add an
   `expand_group` hook? The bug ships either way until one lands.
2. **ZHA:** stay `unsupported`, add `expand_group` (keeps `confirmed`), or send the groupcast (`sent` only)?
3. Is `sent` with silent misses (a member that can't run the timer, a groupcast that never arrives) acceptable
   for a group, given that expansion reports them?
4. Should a group target's result list members, or stay one result for the group?

## What the rig would have to prove

Setup: on each network, a group of at least two lights known to honor `OnWithTimedOff` by unicast; ideally a
third member that doesn't, to see the silent case.

1. `turn_on_for` on the group entity: every member turns on and each turns off on time.
2. The same with `brightness`: level first, then the timer.
3. HA state of the group and members during the timer and after the off, and how long reports take.
4. ZHA: a call as a non-admin user is refused; a call for a group deleted in ZHA is caught by the adapter.
5. Z2M: the command topic the adapter builds for a group, checked against Z2M's log.
