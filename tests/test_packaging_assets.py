"""Packaging regression (WP-III v2.0): runtime assets must be declared as
package data. The v1.4.0 wheel/sdist silently lacked pfword.ps1 and
paper.mplstyle (both are read via Path(__file__).with_name(...) at runtime) —
declared-here + present-next-to-module is the cheap guard; the full
wheel-content proof lives in docs/reports/V2_0_PLATFORM_PACKAGING.md."""
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# (module whose neighbour reads the asset, asset filename)
_RUNTIME_ASSETS = [
    ("paper_factory.paperpal.word.driver", "pfword.ps1"),
    ("paper_factory.figures.build", "paper.mplstyle"),
]


@pytest.mark.parametrize(("module", "asset"), _RUNTIME_ASSETS)
def test_runtime_asset_present_next_to_module(module, asset):
    import importlib

    mod = importlib.import_module(module)
    assert (Path(mod.__file__).resolve().parent / asset).is_file(), (
        f"{asset} must ship next to {module} — it is read via __file__ at runtime"
    )


def test_runtime_assets_declared_as_package_data():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover — py>=3.11 always has it
        pytest.skip("tomllib unavailable")
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    pkg_data = data["tool"]["setuptools"].get("package-data", {})
    declared = {
        pattern
        for patterns in pkg_data.values()
        for pattern in patterns
    }
    for _, asset in _RUNTIME_ASSETS:
        assert f"*.{asset.rsplit('.', 1)[1]}" in declared or asset in declared, (
            f"{asset} missing from [tool.setuptools.package-data] — "
            "it will be absent from wheel/sdist"
        )
