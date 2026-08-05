import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "hosted" / "compose.yaml"

pytestmark = pytest.mark.skipif(
    os.environ.get("THESISTRACE_CONTAINER_ACCEPTANCE") != "1",
    reason="set THESISTRACE_CONTAINER_ACCEPTANCE=1 for container probes",
)

COMPUTE_PROBE = r"""
import os
import socket
from pathlib import Path

assert os.getuid() == 10004
assert Path("/var/lib/thesistrace/working-cache").is_dir()
Path("/var/lib/thesistrace/working-cache/compute-probe").write_text("ok")
assert not Path("/var/lib/thesistrace/objects").exists()
assert not Path("/var/run/docker.sock").exists()
assert "TUSHARE_TOKEN" not in os.environ
status = Path("/proc/self/status").read_text()
capability = next(
    line.split()[1] for line in status.splitlines()
    if line.startswith("CapEff:")
)
assert int(capability, 16) == 0
try:
    Path("/root-boundary-probe").write_text("forbidden")
except OSError as error:
    assert error.errno == 30
else:
    raise AssertionError("root filesystem is writable")
assert Path("/sys/fs/cgroup/memory.max").read_text().strip() == "1073741824"
quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
assert int(quota) / int(period) == 0.75
probe = socket.socket()
probe.settimeout(1)
try:
    probe.connect(("1.1.1.1", 443))
except OSError:
    pass
else:
    raise AssertionError("Compute Worker has general Internet egress")
finally:
    probe.close()
"""

DATA_PROBE = r"""
import os
import socket
from pathlib import Path

assert os.getuid() == 10003
assert not Path("/var/lib/thesistrace/working-cache").exists()
assert not Path("/var/lib/thesistrace/objects").exists()
assert not Path("/var/run/docker.sock").exists()
assert "TUSHARE_TOKEN" in os.environ
assert Path("/sys/fs/cgroup/memory.max").read_text().strip() == "1073741824"
quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
assert int(quota) / int(period) == 0.5
direct = socket.socket()
direct.settimeout(1)
try:
    direct.connect(("1.1.1.1", 443))
except OSError:
    pass
else:
    raise AssertionError("Data Worker has unrestricted Internet egress")
finally:
    direct.close()
allowed = socket.create_connection(("tushare-egress", 8080), timeout=5)
allowed.sendall(
    b"CONNECT api.tushare.pro:443 HTTP/1.1\r\n"
    b"Host: api.tushare.pro:443\r\n\r\n"
)
assert allowed.recv(4096).startswith(
    b"HTTP/1.1 200 Connection Established"
)
allowed.close()
blocked = socket.create_connection(("tushare-egress", 8080), timeout=5)
blocked.sendall(
    b"CONNECT example.com:443 HTTP/1.1\r\n"
    b"Host: example.com:443\r\n\r\n"
)
assert blocked.recv(4096).startswith(b"HTTP/1.1 403 Forbidden")
blocked.close()
"""

STORAGE_PROBE = r"""
import os
from pathlib import Path

assert os.getuid() == 10005
assert Path("/var/lib/thesistrace/objects").is_dir()
assert not Path("/var/lib/thesistrace/working-cache").exists()
assert "THESISTRACE_DATABASE_URL" not in os.environ
assert not Path("/var/run/docker.sock").exists()
"""


def compose_command(project: str, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--project-directory",
        str(ROOT),
        "-f",
        str(COMPOSE),
        *arguments,
    ]
