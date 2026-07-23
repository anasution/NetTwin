# Network Digital Twin (NDT)

A software model of your network that lets you simulate failures, trace packet paths, detect configuration drift, and predict problems — without touching real devices.

## What is it?

NDT creates a "digital copy" of your network from a YAML file describing your routers, firewalls, and their routing tables. You can then:

- Trace where a packet goes from router A to IP address B (hop by hop)
- Simulate a link failure and see which customers are affected
- Compare your topology file against live device state to detect unauthorized changes
- Score the risk of a config change before pushing it to production
- Automatically identify the root cause of an outage

**No real traffic is affected.** Everything runs as a simulation.

## Quick Start

```bash
# Load and validate your topology
python -m ndt load topology/example.yaml

# Trace a packet path
python -m ndt trace R1-CORE 203.0.113.1 --vrf default

# Simulate a link failure
python -m ndt fail-link R1-CORE R2-EDGE
python -m ndt trace R1-CORE 203.0.113.1 --vrf default
python -m ndt restore-link R1-CORE R2-EDGE
```

## Installation

All commands must be run inside WSL Ubuntu-24.04 with the `ndt-env` virtual environment active.

```bash
source ~/ndt-env/bin/activate
pip install -r requirements.txt
pip install -e .
docker compose up -d
```

## Architecture

The NDT models a network as three layers:

1. **Topology** — YAML file describing devices, interfaces, routes
2. **Device abstraction** — vendor-specific models (Cisco, Juniper, Palo Alto)
3. **Network graph** — physical links and VRF/VSys relationships

The path tracer performs hop-by-hop forwarding simulation using RIB lookups and link state.

## Supported Vendors

| Vendor | Device Type |
|---|---|
| Cisco IOS/XE | Routers, switches |
| Juniper Junos | Routers (MX/EX) |
| Palo Alto PAN-OS | Firewalls (VSys-aware) |

## Commands

### Topology & Simulation
```bash
ndt load topology/example.yaml
ndt trace R1-CORE 203.0.113.1 --vrf default
ndt fail-link R1-CORE R2-EDGE
ndt restore-link R1-CORE R2-EDGE
```

### Scraper
```bash
ndt scrape --inventory topology/device-inventory.csv --output topology/live.yaml
```

### Batfish
```bash
ndt batfish-validate --snapshot batfish-snapshots/current
ndt batfish-diff --current batfish-snapshots/current --proposed batfish-snapshots/proposed
```

### AIOps
```bash
ndt aiops-anomaly
ndt aiops-risk --current batfish-snapshots/current --proposed batfish-snapshots/proposed
ndt aiops-rca
ndt aiops-capacity --days 90
ndt aiops-blast-radius R2-EDGE
```

## Testing

```bash
pytest
pytest tests/test_path_tracer.py
pytest tests/test_path_tracer.py::test_trace_default_vrf_success
```

## License

Viasat Internal Use
