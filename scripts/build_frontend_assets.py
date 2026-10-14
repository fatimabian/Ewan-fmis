"""Build deterministic, minified FMIS CSS bundles without Node dependencies."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

CORE_SOURCES = (
    "css/bootstrap-compat.css",
    "css/fmis.css",
    "css/fmis-polish.css",
    "css/tables.css",
    "css/agriculture-theme.css",
    "css/typography.css",
    "css/record-detail.css",
    "css/admin-mobile.css",
    "css/form-validation.css",
    "css/system-responsive.css",
    "css/human-ui.css",
    "css/date-picker.css",
    "css/table-layout.css",
)


def minify_css(value: str) -> str:
    value = re.sub(r"/\*(?!\!)[\s\S]*?\*/", "", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*([{}:;,>])\s*", r"\1", value)
    value = re.sub(r";}", "}", value)
    return value.strip() + "\n"


def icon_subset() -> str:
    used: set[str] = set()
    for folder, suffix in ((ROOT / "templates", "*.html"), (STATIC / "js", "*.js")):
        for path in folder.rglob(suffix):
            used.update(re.findall(r"\bbi-[a-z0-9-]+\b", path.read_text(encoding="utf-8")))

    source = (STATIC / "vendor/bootstrap-icons/bootstrap-icons.min.css").read_text(
        encoding="utf-8"
    )
    font_rule = re.search(r"@font-face\{.*?\}", source)
    if not font_rule:
        raise RuntimeError("Bootstrap Icons font rule was not found")
    font_css = font_rule.group(0).replace("font-display:block", "font-display:swap")
    font_css = font_css.replace('url("fonts/', 'url("../vendor/bootstrap-icons/fonts/')
    base_css = (
        '.bi::before,[class*=" bi-"]::before,[class^=bi-]::before{'
        "display:inline-block;font-family:bootstrap-icons!important;font-style:normal;"
        "font-weight:400!important;font-variant:normal;text-transform:none;line-height:1;"
        "vertical-align:-.125em;-webkit-font-smoothing:antialiased;"
        "-moz-osx-font-smoothing:grayscale}"
    )
    rules: list[str] = []
    missing: list[str] = []
    for icon in sorted(used):
        match = re.search(rf"\.{re.escape(icon)}::before\{{content:\"([^\"]+)\"\}}", source)
        if match:
            rules.append(f'.{icon}::before{{content:"{match.group(1)}"}}')
        else:
            missing.append(icon)
    if missing:
        raise RuntimeError(f"Missing Bootstrap Icon definitions: {', '.join(missing)}")
    return font_css + base_css + "".join(rules)


def bundle(sources: tuple[str, ...], include_icons: bool = False) -> str:
    parts = [icon_subset()] if include_icons else []
    parts.extend((STATIC / source).read_text(encoding="utf-8") for source in sources)
    return minify_css("\n".join(parts))


def outputs() -> dict[Path, str]:
    return {
        STATIC / "css/fmis-core.min.css": bundle(CORE_SOURCES, include_icons=True),
        STATIC / "css/fmis-overrides.min.css": bundle(
            ("css/dark-mode.css", "css/shape-system.css")
        ),
        STATIC / "css/fmis-public.min.css": bundle(
            ("css/typography.css", "css/shape-system.css", "css/landing-showcase.css"),
            include_icons=True,
        ),
        STATIC / "css/staff-dashboard.min.css": bundle(("css/staff-dashboard.css",)),
        STATIC / "css/bootstrap-icons-fmis.min.css": minify_css(icon_subset()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if bundles are stale")
    args = parser.parse_args()
    stale: list[str] = []
    for path, content in outputs().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"built {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.1f} KiB)")
    if stale:
        print("Stale frontend bundles: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
