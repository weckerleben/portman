"""Hatch build hook: bundle the built SPA into the package before packaging.

The web UI is built in ``frontend/`` and lives at ``frontend/dist`` in a dev
checkout. For installable artifacts (sdist/wheel → pip/pipx/uv/brew) the daemon
must carry the SPA itself, so this hook copies ``frontend/dist`` into
``portman/web`` at build time. Combined with the ``artifacts`` setting in
``pyproject.toml``, those files (otherwise gitignored) ship in the package.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class BundleSPAHook(BuildHookInterface):
    PLUGIN_NAME = "bundle-spa"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)  # the backend/ directory
        dist = root.parent / "frontend" / "dist"
        target = root / "portman" / "web"

        if dist.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(dist, target)
            self.app.display_info(f"bundle-spa: copied {dist} -> {target}")
        elif not target.is_dir():
            self.app.display_warning(
                "bundle-spa: frontend/dist not found and portman/web missing — "
                "the build will not serve the web UI. Run `npm run build` in "
                "frontend/ first."
            )
