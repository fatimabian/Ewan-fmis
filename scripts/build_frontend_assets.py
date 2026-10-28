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
    "css/table-toolbar.css",
)

CORE_JS_SOURCES = (
    "js/fmis.js",
    "js/password-toggle.js",
    "js/form-validation.js",
    "js/date-picker.js",
    "js/table-toolbar.js",
)


def minify_css(value: str) -> str:
    value = re.sub(r"/\*(?!\!)[\s\S]*?\*/", "", value)
    value = re.sub(r"\s+", " ", value)
    # A space before `:is()` / `:not()` can be a descendant combinator. Do not
    # strip whitespace before colons or selectors such as `body :is(button)`
    # become the very different (and usually impossible) `body:is(button)`.
    value = re.sub(r"\s*([{};,>])\s*", r"\1", value)
    value = re.sub(r":\s+", ":", value)
    value = re.sub(r";}", "}", value)
    return value.strip() + "\n"


def compact_js(value: str) -> str:
    """Safely compact checked-in JS while retaining newlines for ASI semantics."""
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        lines.append(stripped)
    return "\n".join(lines) + "\n"


def js_bundle(sources: tuple[str, ...]) -> str:
    return ";\n".join(
        compact_js((STATIC / source).read_text(encoding="utf-8")).rstrip()
        for source in sources
    ) + "\n"


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
            ("css/typography.css", "css/landing-showcase.css", "css/shape-system.css"),
            include_icons=True,
        ),
        STATIC / "css/fmis-auth.min.css": bundle(
            (
                "css/auth.css",
                "css/auth-enhancements.css",
                "css/typography.css",
                "css/form-validation.css",
                "css/shape-system.css",
            ),
            include_icons=True,
        ),
        STATIC / "css/fmis-legal.min.css": bundle(
            ("css/typography.css", "css/shape-system.css")
        ),
        STATIC / "css/staff-dashboard.min.css": bundle(("css/staff-dashboard.css",)),
        STATIC / "css/bootstrap-icons-fmis.min.css": minify_css(icon_subset()),
        STATIC / "js/fmis-core.min.js": js_bundle(CORE_JS_SOURCES),
        STATIC / "js/landing.min.js": js_bundle(("js/landing.js",)),
        STATIC / "js/staff-dashboard.min.js": js_bundle(("js/staff-dashboard.js",)),
        STATIC / "js/form-validation.min.js": js_bundle(("js/form-validation.js",)),
        STATIC / "js/password-toggle.min.js": js_bundle(("js/password-toggle.js",)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if bundles are stale")
    args = parser.parse_args()
    selector_probe = "body :is(button){color:red}\n"
    if minify_css("body :is(button) { color: red; }") != selector_probe:
        raise RuntimeError("CSS minification changed descendant pseudo-class semantics")
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
