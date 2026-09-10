"""Checks that the shipped metadata matches the code.

These catch the mistakes that only surface once Home Assistant loads the
integration: an entity whose translation key was never declared, a manifest
that drifted, or a language file that fell behind.
"""

from __future__ import annotations

import ast
import json
import pathlib
import struct
import unittest
import zlib

from _loader import COMPONENT_DIR

REPO_ROOT = COMPONENT_DIR.parents[1]

PLATFORMS = (
    "binary_sensor",
    "button",
    "camera",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
)


def _translation_keys(platform: str) -> set[str]:
    """Return every translation key declared by a platform module."""
    tree = ast.parse((COMPONENT_DIR / f"{platform}.py").read_text())
    keys: set[str] = set()

    for node in ast.walk(tree):
        # _attr_translation_key = "..."
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "_attr_translation_key"
                    and isinstance(node.value, ast.Constant)
                ):
                    keys.add(node.value.value)
        # translation_key="..." in an entity description
        if isinstance(node, ast.keyword) and node.arg == "translation_key":
            if isinstance(node.value, ast.Constant):
                keys.add(node.value.value)
            elif isinstance(node.value, ast.JoinedStr):
                # f"night_{trigger}" over the known trigger names
                const = ast.parse((COMPONENT_DIR / "const.py").read_text())
                for item in ast.walk(const):
                    if (
                        isinstance(item, ast.AnnAssign)
                        and isinstance(item.target, ast.Name)
                        and item.target.id == "NIGHT_TRIGGERS"
                        and isinstance(item.value, ast.Tuple)
                    ):
                        keys.update(
                            f"night_{elt.value}"
                            for elt in item.value.elts
                            if isinstance(elt, ast.Constant)
                        )
    return keys


class ManifestTest(unittest.TestCase):
    """The manifest declares what Home Assistant and HACS need."""

    def setUp(self) -> None:
        self.manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text())

    def test_required_keys_are_present(self):
        for key in (
            "domain",
            "name",
            "config_flow",
            "documentation",
            "iot_class",
            "version",
        ):
            with self.subTest(key=key):
                self.assertIn(key, self.manifest)

    def test_domain_matches_the_folder_and_the_constant(self):
        self.assertEqual(self.manifest["domain"], COMPONENT_DIR.name)
        const = (COMPONENT_DIR / "const.py").read_text()
        self.assertIn(f'DOMAIN: Final = "{self.manifest["domain"]}"', const)

    def test_it_is_a_polled_local_integration_with_no_dependencies(self):
        self.assertEqual(self.manifest["iot_class"], "local_polling")
        self.assertEqual(self.manifest["requirements"], [])


class TranslationTest(unittest.TestCase):
    """Every declared translation key resolves, in every language."""

    def setUp(self) -> None:
        self.strings = json.loads((COMPONENT_DIR / "strings.json").read_text())
        self.languages = {
            path.stem: json.loads(path.read_text())
            for path in (COMPONENT_DIR / "translations").glob("*.json")
        }

    def test_english_translations_mirror_strings_json(self):
        self.assertEqual(self.languages["en"], self.strings)

    def test_every_language_has_the_same_keys(self):
        def keys(node, prefix=""):
            found = set()
            for key, value in node.items():
                found.add(prefix + key)
                if isinstance(value, dict):
                    found |= keys(value, f"{prefix}{key}.")
            return found

        reference = keys(self.strings)
        for language, payload in self.languages.items():
            with self.subTest(language=language):
                self.assertEqual(keys(payload), reference)

    def test_every_entity_translation_key_is_declared(self):
        for platform in PLATFORMS:
            declared = self.strings["entity"].get(platform, {})
            for key in _translation_keys(platform):
                with self.subTest(platform=platform, key=key):
                    self.assertIn(key, declared)

    def test_every_flow_step_is_translated(self):
        flow = (COMPONENT_DIR / "config_flow.py").read_text()
        declared = self.strings["config"]["step"]
        for step in ("user", "reconfigure", "reauth_confirm"):
            with self.subTest(step=step):
                self.assertIn(f'step_id="{step}"', flow)
                self.assertIn(step, declared)

    def test_every_abort_reason_is_translated(self):
        flow = (COMPONENT_DIR / "config_flow.py").read_text()
        aborts = self.strings["config"]["abort"]
        self.assertIn("another_device", aborts)
        self.assertIn('reason="another_device"', flow)
        # Raised by the Home Assistant helpers rather than named in our code.
        for reason in (
            "already_configured",
            "reauth_successful",
            "reconfigure_successful",
        ):
            with self.subTest(reason=reason):
                self.assertIn(reason, aborts)

    def test_the_config_flow_errors_are_all_translated(self):
        flow = (COMPONENT_DIR / "config_flow.py").read_text()
        for error in ("cannot_connect", "invalid_auth", "unknown"):
            with self.subTest(error=error):
                self.assertIn(f'"{error}"', flow)
                self.assertIn(error, self.strings["config"]["error"])


class IconsTest(unittest.TestCase):
    """icons.json is validated by hassfest, so keep it in step with the code."""

    def setUp(self) -> None:
        self.icons = json.loads((COMPONENT_DIR / "icons.json").read_text())
        self.strings = json.loads((COMPONENT_DIR / "strings.json").read_text())

    def test_every_icon_maps_to_a_declared_entity(self):
        for platform, entries in self.icons["entity"].items():
            declared = self.strings["entity"].get(platform, {})
            for key in entries:
                with self.subTest(platform=platform, key=key):
                    self.assertIn(key, declared)

    def test_every_entity_has_an_icon(self):
        for platform in PLATFORMS:
            for key in _translation_keys(platform):
                with self.subTest(platform=platform, key=key):
                    self.assertIn(key, self.icons["entity"].get(platform, {}))

    def test_entity_icons_use_the_default_key(self):
        for platform, entries in self.icons["entity"].items():
            for key, spec in entries.items():
                with self.subTest(platform=platform, key=key):
                    self.assertIn("default", spec)
                    self.assertTrue(spec["default"].startswith("mdi:"))

    def test_every_service_has_an_icon(self):
        for name in self.strings["services"]:
            with self.subTest(service=name):
                self.assertIn(name, self.icons["services"])
                self.assertTrue(
                    self.icons["services"][name]["service"].startswith("mdi:")
                )


class BrandIconTest(unittest.TestCase):
    """HACS reads brand assets from inside the integration folder.

    It looks for ``custom_components/<domain>/brand/icon.png`` first and only
    falls back to the brands repository when that is absent, so these files
    are what make the integration show an icon in HACS.
    """

    # name -> required square size, or None when only the height is fixed.
    REQUIRED: dict[str, int | None] = {
        "icon.png": 256,
        "icon@2x.png": 512,
        "logo.png": None,
    }

    def setUp(self) -> None:
        self.brand = COMPONENT_DIR / "brand"

    def _header(self, path: pathlib.Path) -> tuple[int, int, int, int]:
        """Return (width, height, bit depth, colour type) from the PNG IHDR."""
        raw = path.read_bytes()
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n", "not a PNG")
        self.assertEqual(raw[12:16], b"IHDR", "IHDR is not the first chunk")
        return struct.unpack(">IIBB", raw[16:26])

    def test_hacs_finds_the_icon_where_it_looks_for_it(self):
        self.assertTrue(
            (self.brand / "icon.png").is_file(),
            "HACS expects custom_components/<domain>/brand/icon.png",
        )

    def test_every_asset_has_the_shape_hacs_expects(self):
        for name, size in self.REQUIRED.items():
            with self.subTest(asset=name):
                path = self.brand / name
                self.assertTrue(path.is_file(), f"{name} is missing")
                width, height, depth, colour = self._header(path)
                self.assertEqual(depth, 8)
                self.assertEqual(colour, 6, "must be RGBA, brands wants alpha")
                if size is None:
                    self.assertEqual(height, 256, "logo.png must be 256 tall")
                else:
                    self.assertEqual((width, height), (size, size))

    def test_the_icon_is_not_mostly_transparent_padding(self):
        path = self.brand / "icon.png"
        width, height, _, _ = self._header(path)
        pixels = _decode_rgba(path, width, height)

        opaque_columns = [
            x for x in range(width) if any(pixels[y][x][3] > 8 for y in range(height))
        ]
        opaque_rows = [
            y for y in range(height) if any(pixels[y][x][3] > 8 for x in range(width))
        ]
        self.assertLessEqual(min(opaque_columns), 24)
        self.assertGreaterEqual(max(opaque_columns), width - 25)
        self.assertLessEqual(min(opaque_rows), 24)
        self.assertGreaterEqual(max(opaque_rows), height - 25)


def _decode_rgba(path: pathlib.Path, width: int, height: int):
    """Return the image as rows of (r, g, b, a), undoing PNG filtering."""
    raw = path.read_bytes()
    idat = bytearray()
    offset = 8
    while offset < len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        tag = raw[offset + 4 : offset + 8]
        if tag == b"IDAT":
            idat += raw[offset + 8 : offset + 8 + length]
        offset += 12 + length

    data = zlib.decompress(bytes(idat))
    stride = width * 4
    rows = []
    previous = bytearray(stride)
    pos = 0
    for _ in range(height):
        filter_type = data[pos]
        line = bytearray(data[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up = previous[i]
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif filter_type == 4:
                upper_left = previous[i - 4] if i >= 4 else 0
                p = left + up - upper_left
                candidates = (
                    (abs(p - left), 0, left),
                    (abs(p - up), 1, up),
                    (abs(p - upper_left), 2, upper_left),
                )
                line[i] = (line[i] + min(candidates)[2]) & 0xFF
        rows.append([tuple(line[i : i + 4]) for i in range(0, stride, 4)])
        previous = line
    return rows


if __name__ == "__main__":
    unittest.main()
