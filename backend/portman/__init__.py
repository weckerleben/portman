"""portman — local port & service manager.

A local control plane that lets you authorize, reserve, supervise and monitor
every port and dev service on your machine.
"""

from importlib.metadata import PackageNotFoundError, version as _dist_version

try:
    # Single source of truth: the version declared in pyproject.toml, read from
    # the installed distribution metadata so it can never drift from the package.
    __version__ = _dist_version("portreeve")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
