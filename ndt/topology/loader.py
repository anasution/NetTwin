"""Load and validate topology from YAML or JSON files."""
from __future__ import annotations
import json
from pathlib import Path
import yaml
from ndt.topology.schema import Topology, DeviceConfig


def load(path: str | Path) -> Topology:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) if p.suffix in {".yaml", ".yml"} else json.loads(raw)
    return Topology.model_validate(data)


def load_devices(path: str | Path) -> list[DeviceConfig]:
    return load(path).devices


def summary(topology: Topology) -> str:
    lines = [f"Loaded {len(topology.devices)} devices:"]
    for d in topology.devices:
        instances = d.routing_instances()
        kind = "VSys" if d.type == "palo_alto" else "VRFs"
        names = ", ".join(ri.name for ri in instances)
        lines.append(f"  {d.name} ({d.type}): {kind}: {names}")
    return "\n".join(lines)
