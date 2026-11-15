"""Plan 40 C5: the client guide's Kubernetes recipe keeps log buffers on a
volume that outlives the pod, so a buffer kept after a store outage or a
kill can be shipped later from another pod."""
import re
from pathlib import Path

import yaml

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "vmn-exp" / "client-guide.md"


def _recipe():
    section = GUIDE.read_text().split("### Jobs without git", 1)[1].split("\n### ", 1)[0]
    block = re.search(r"```yaml\n(.*?)```", section, re.S).group(1)
    return yaml.safe_load(block)


def test_the_kubernetes_recipe_puts_the_cache_dir_on_a_mounted_volume():
    recipe = _recipe()
    container = recipe["containers"][0]
    env = {e["name"]: e["value"] for e in container["env"]}
    cache_dir = env["VMN_EXP_CACHE_DIR"]
    mounts = [m for m in container["volumeMounts"]
              if cache_dir == m["mountPath"] or cache_dir.startswith(m["mountPath"] + "/")]
    assert len(mounts) == 1, (cache_dir, container["volumeMounts"])
    volume = next(v for v in recipe["volumes"] if v["name"] == mounts[0]["name"])
    assert "emptyDir" not in volume
    assert "persistentVolumeClaim" in volume or "hostPath" in volume
