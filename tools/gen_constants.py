#!/usr/bin/env python3
"""Generate constants using installed headers and a C compiler (development only)."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    flags = subprocess.check_output(["curl-config", "--cflags"], text=True).split()
    text = subprocess.check_output(
        ["cc", *flags, "-E", "-P", "-xc", "-"],
        input="#include <curl/curl.h>\n",
        text=True,
    )
    groups = {
        "CurlOpt": "CURLOPT_",
        "CurlInfo": "CURLINFO_",
        "CurlCode": "CURLE_",
        "MultiOpt": "CURLMOPT_",
        "MultiCode": "CURLM_",
        "HttpVersion": "CURL_HTTP_VERSION_",
        "ProxyType": "CURLPROXY_",
        "SslVersion": "CURL_SSLVERSION_",
        "IpResolve": "CURL_IPRESOLVE_",
    }
    names = sorted(
        set(
            re.findall(
                r"\b(?:CURLOPT_|CURLINFO_|CURLE_|CURLMOPT_|CURLM_|CURL_HTTP_VERSION_|"
                r"CURLPROXY_|CURL_SSLVERSION_|CURL_IPRESOLVE_)[A-Z0-9_]+\b",
                text,
            )
        )
    )
    names = [n for n in names if not n.endswith(("LAST", "LASTONE"))]
    # Macros disappear in preprocessed output; collect object-like integer macros too.
    macros = subprocess.check_output(
        ["cc", *flags, "-dM", "-E", "-xc", "-"],
        input="#include <curl/curl.h>\n",
        text=True,
    )
    for group, prefix in {
        "CurlAuth": "CURLAUTH_",
        "Protocol": "CURLPROTO_",
        "SslOpt": "CURLSSLOPT_",
        "CurlPause": "CURLPAUSE_",
    }.items():
        groups[group] = prefix
        names += re.findall(rf"^#define ({prefix}[A-Z0-9_]+) ", macros, re.M)
    names += re.findall(r"^#define (CURL_IPRESOLVE_[A-Z0-9_]+) ", macros, re.M)
    names = sorted(set(names))
    source = "#include <stdio.h>\n#include <curl/curl.h>\nint main(void) {\n"
    source += "\n".join(f'printf("{n} %lld\\n", (long long){n});' for n in names)
    source += "\nreturn 0; }\n"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / "probe.c").write_text(source)
        subprocess.run(
            [
                os.environ.get("CC", "cc"),
                *flags,
                "-Wno-deprecated-declarations",
                str(path / "probe.c"),
                "-o",
                str(path / "probe"),
            ],
            check=True,
        )
        values = dict(
            line.split()
            for line in subprocess.check_output([str(path / "probe")], text=True).splitlines()
        )
    lines = [
        '"""Generated libcurl constants. Run tools/gen_constants.py to regenerate."""',
        "",
        "from enum import IntEnum, IntFlag",
        "",
    ]
    for group, prefix in groups.items():
        base = "IntFlag" if group in {"CurlAuth", "Protocol", "SslOpt", "CurlPause"} else "IntEnum"
        lines += [
            "",
            f"class {group}({base}):",
            f'    """{prefix} constants from libcurl headers."""',
            "",
        ]
        for name, value in sorted(values.items(), key=lambda item: (int(item[1]), item[0])):
            if name.startswith(prefix):
                member = name[len(prefix) :]
                if member[0].isdigit():
                    member = "V" + member
                lines.append(f"    {member} = {value}")
    # Preserve semantic pointer kinds: numeric option ranges alone are NOT sufficient.
    raw = subprocess.check_output(
        ["cc", *flags, "-E", "-fdirectives-only", "-xc", "-"],
        input="#include <curl/curl.h>\n",
        text=True,
    )
    kinds = re.findall(r"CURLOPT(?:DEPRECATED)?\(\s*(CURLOPT_\w+),\s*CURLOPTTYPE_(\w+)", raw)
    lines += ["", "", "OPTION_KINDS: dict[int, str] = {"]
    for name, kind in kinds:
        if name in values:
            lines.append(f"    {values[name]}: {kind.lower()!r},  # {name}")
    lines += ["}", ""]
    target = ROOT / "src/curlight/constants.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines))
    print(f"Wrote {target}: {len(values)} constants, {len(kinds)} option types")


if __name__ == "__main__":
    main()
