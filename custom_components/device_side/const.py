DOMAIN = "device_side"
NAME = "Device Side"

# The light.turn_on fields a feature may accept, under their light.turn_on names.
LIGHT_FIELDS = ("brightness", "color_temp_kelvin", "hs_color", "rgb_color", "xy_color", "transition")

# Whole-call ceiling for one cell's execute(); a cell still running after this is reported rejected.
CELL_TIMEOUT_S = 30
