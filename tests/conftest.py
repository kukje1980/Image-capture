import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory):
    from fundusview.demo import write_demo_folder

    root = tmp_path_factory.mktemp("demo_drop")
    write_demo_folder(root, small=True)
    return root
