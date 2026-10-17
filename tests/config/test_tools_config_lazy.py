import subprocess
import sys

import pytest


@pytest.mark.parametrize("first_import", ["nanobot.session", "nanobot.context_graph"])
def test_tools_config_builds_after_an_import_order_that_hits_the_schema_cycle(first_import):
    code = f"import {first_import}; from nanobot.config.schema import ToolsConfig; ToolsConfig(); print('ok')"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr[-400:]
