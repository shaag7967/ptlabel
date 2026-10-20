"""Run the tests in English with throwaway settings and font folders."""

import os
import tempfile

_home = tempfile.TemporaryDirectory()
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = os.path.join(_home.name, var.lower())
os.environ["LANGUAGE"] = "en"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
