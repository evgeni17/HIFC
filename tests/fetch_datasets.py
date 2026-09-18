# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Скачивает buildingSMART Certification-datasets (CC BY 4.0) в tests/datasets/.

    python fetch_datasets.py            # или hython fetch_datasets.py

Источник: https://github.com/buildingSMART/Certification-datasets
Данные © buildingSMART International Ltd., лицензия CC BY 4.0 — в репозиторий HIFC не входят.
"""
import io
import os
import re
import urllib.request
import zipfile

URL = "https://codeload.github.com/buildingSMART/Certification-datasets/zip/refs/heads/main"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "datasets")


def main():
    print("Downloading", URL)
    data = urllib.request.urlopen(URL, timeout=120).read()
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if not name.lower().endswith(".ifc") and not name.endswith("LICENSE"):
                continue
            parts = name.split("/")[1:]  # убираем корневую папку архива
            if not parts:
                continue
            # "IFC 4.0.2.1 (IFC 4 ADD2 TC1)" -> "4.0.2.1"
            parts[0] = re.sub(r"^IFC ([0-9.]+).*$", r"\1", parts[0])
            dst = os.path.join(OUT, *parts)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(z.read(name))
            n += 1
    print("Saved %d files to %s" % (n, OUT))


if __name__ == "__main__":
    main()
