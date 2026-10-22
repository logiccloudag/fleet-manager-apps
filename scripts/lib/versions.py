"""Version arithmetic of the weekly upstream check (scripts/upstream-check.py).

A version or image tag has a *shape*: a prefix, a numeric core of one to
three components and a suffix, for example "v" + "3.7.14" + "" or
"" + "2.9.1" + "-alpine". The newest upstream release of a pin is the
highest tag of the same shape (same prefix, same suffix, same number of
core components). Anything else is ignored, which drops pre-releases
("2.9.2-rc1-alpine", "3.0.0-beta.1"), nightlies and other variants
("v3.7.9-nanoserver-ltsc2022").

Pure functions only; tested by scripts/tests/test_versions.py.
"""

import re

_SHAPE = re.compile(r"^(?P<prefix>[^0-9]*)(?P<core>\d+(?:\.\d+){0,2})(?P<suffix>.*)$")
_UNSTABLE = re.compile(r"(?i)(?:^|[.\-_+])(?:rc|alpha|beta|pre|preview|dev|nightly|snapshot)\d*(?:$|[.\-_+])")
BUMPS = ("none", "patch", "minor", "major")


def shape(tag):
    """(prefix, core tuple, suffix, number of core components), or None."""
    m = _SHAPE.match(tag or "")
    if not m:
        return None
    if m.group("prefix") not in ("", "v"):
        return None
    parts = tuple(int(p) for p in m.group("core").split("."))
    return m.group("prefix"), parts, m.group("suffix"), len(parts)


def is_stable(tag):
    """False for a tag that names a pre-release or a nightly."""
    return shape(tag) is not None and not _UNSTABLE.search(tag)


def core(tag):
    """The numeric core padded to three components, for comparisons."""
    s = shape(tag)
    if s is None:
        raise ValueError(f"not a version: {tag!r}")
    parts = s[1]
    return parts + (0,) * (3 - len(parts))


def classify(current, latest):
    """The bump from `current` to `latest`: none, patch, minor or major.

    "2.7" vs "3.0" is major, "2.7.10" vs "2.7.11" patch, equal or lower
    versions none."""
    a, b = core(current), core(latest)
    if b <= a:
        return "none"
    if b[0] != a[0]:
        return "major"
    if b[1] != a[1]:
        return "minor"
    return "patch"


def max_bump(*bumps):
    return max(bumps, key=BUMPS.index) if bumps else "none"


def newest(current, candidates):
    """The highest stable candidate of the same shape as `current`, or
    `current` itself when there is no higher one."""
    cs = shape(current)
    if cs is None:
        raise ValueError(f"not a version: {current!r}")
    best = current
    for tag in candidates:
        s = shape(tag)
        if s is None or not is_stable(tag):
            continue
        if (s[0], s[2], s[3]) != (cs[0], cs[2], cs[3]):
            continue
        if core(tag) > core(best):
            best = tag
    return best


def retag(current, new_core):
    """`current` with its core replaced, keeping prefix and suffix:
    retag("13.2.3-distroless", "13.2.4") == "13.2.4-distroless"."""
    s = shape(current)
    if s is None:
        raise ValueError(f"not a version: {current!r}")
    n = shape(new_core)
    if n is None:
        raise ValueError(f"not a version: {new_core!r}")
    return f"{s[0]}{'.'.join(str(p) for p in n[1])}{s[2]}"


def bump(version, level):
    """SemVer bump of an X.Y.Z version: patch, minor or major."""
    major, minor, patch = core(version)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return version
