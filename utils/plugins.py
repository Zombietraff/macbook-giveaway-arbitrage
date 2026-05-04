"""Discovery and activation helpers for mini-game plugins."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import config
from db.models import get_setting, set_setting

ACTIVE_PLUGIN_SETTING = "active_plugin_key"
DEFAULT_PLUGIN_KEY = "cherry-charm"
PLUGINS_DIR = config.BASE_DIR / "plagins"


@dataclass(frozen=True)
class PluginManifest:
    key: str
    name: str
    webapp_path: str
    build_dir: str
    package_dir: str
    enabled: bool


def _load_manifest(path: Path) -> PluginManifest:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return PluginManifest(
        key=str(data["key"]),
        name=str(data["name"]),
        webapp_path=str(data.get("webapp_path", "/")),
        build_dir=str(data.get("build_dir", "dist")),
        package_dir=str(data.get("package_dir", ".")),
        enabled=bool(data.get("enabled", True)),
    )


def list_plugins(include_disabled: bool = False) -> list[PluginManifest]:
    """Read plugin manifests from plagins/*/plugin.manifest.json."""
    plugins: list[PluginManifest] = []
    for manifest_path in sorted(PLUGINS_DIR.glob("*/plugin.manifest.json")):
        try:
            plugin = _load_manifest(manifest_path)
        except Exception:
            continue
        if plugin.enabled or include_disabled:
            plugins.append(plugin)
    return plugins


def get_plugin(plugin_key: str) -> PluginManifest | None:
    """Find one enabled plugin by key."""
    for plugin in list_plugins():
        if plugin.key == plugin_key:
            return plugin
    return None


def build_plugin_webapp_url(plugin: PluginManifest, base_url: str | None = None) -> str:
    """Build public WebApp URL for a plugin manifest."""
    root_url = (base_url or config.WEBAPP_URL).rstrip("/")
    path = plugin.webapp_path.strip()
    if not path or path == "/":
        return root_url
    return urljoin(f"{root_url}/", path.lstrip("/"))


async def get_active_plugin_key() -> str:
    """Return active plugin key stored in settings, falling back to default."""
    plugin_key = await get_setting(ACTIVE_PLUGIN_SETTING)
    if plugin_key and get_plugin(plugin_key):
        return plugin_key
    return DEFAULT_PLUGIN_KEY


async def get_active_webapp_url() -> str:
    """Return the public WebApp URL for the active plugin."""
    plugin_key = await get_active_plugin_key()
    plugin = get_plugin(plugin_key)
    if not plugin:
        return config.WEBAPP_URL
    return build_plugin_webapp_url(plugin)


async def set_active_plugin_key(plugin_key: str) -> PluginManifest:
    """Validate and store active plugin key."""
    plugin = get_plugin(plugin_key)
    if not plugin:
        raise ValueError("unknown_plugin")
    await set_setting(ACTIVE_PLUGIN_SETTING, plugin.key)
    return plugin
