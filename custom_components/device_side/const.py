DOMAIN = "device_side"
NAME = "Device Side"

# The light.turn_on fields a action may accept, under their light.turn_on names.
LIGHT_FIELDS = ("brightness", "color_temp_kelvin", "hs_color", "rgb_color", "xy_color", "transition")

# Whole-call ceiling for one adapter's execute(); an adapter still running after this is reported rejected.
ADAPTER_TIMEOUT_S = 30

# Hue fades: hide the bridge's end-value and late reports from HA and show device_side's predictions instead.
CONF_PREDICTED_STATE = "predicted_state"
PREDICTED_STATE_DEFAULT = True
