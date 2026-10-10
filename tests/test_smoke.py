import annualyst


def test_package_imports_with_version() -> None:
    assert annualyst.__version__ == "0.1.0"
