"""Standalone SDK probes; console logs can be redirected to ignored evidence paths."""

from openjiuwen.core.common.logging.log_config import (
    configure_log_config,
    get_log_config_snapshot,
)

# The SDK defaults to files under cwd. This probe must not create runtime logs
# alongside source code; keep all diagnostic levels, only change the sinks.
_config = get_log_config_snapshot()
for _sink in ("output", "interface_output", "performance_output"):
    _config[_sink] = ["console"]
configure_log_config(_config)
