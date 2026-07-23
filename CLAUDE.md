# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

All package installation and execution must be done inside WSL Ubuntu-24.04 virtualenv (`~/ndt-env`). The CLI is invoked as:

```bash
python -m ndt <command> [options]
# or with auto env-var prefix NDT_*
```

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run a single test file
pytest tests/test_path_tracer.py

# Run a single test by name
pytest tests/test_path_tracer.py::test_trace_default_vrf_success

# Start supporting services (Batfish, SuzieQ, MLflow)
docker compose up -d

# Load and validate a topology YAML
python -m ndt load topology/example.yaml

# Trace a forwarding path
python -m ndt trace R1-CORE 203.0.113.1 --vrf default

# Simulate link failure / restore
python -m ndt fail-link R1-CORE R2-EDGE
python -m ndt restore-link R1-CORE R2-EDGE

# Scrape live devices → topology YAML
python -m ndt scrape --inventory topology/device-inventory.csv --output topology/live.yaml

# Batfish config validation and diff
python -m ndt batfish-validate --snapshot batfish-snapshots/current
python -m ndt batfish-diff --current batfish-snapshots/current --proposed batfish-snapshots/proposed

# SuzieQ live polling and drift detection
python -m ndt suzieq-poll --inventory topology/device-inventory.csv
python -m ndt suzieq-drift --topology topology/example.yaml

# AIOps commands
python -m ndt aiops-anomaly
python -m ndt aiops-rca
python -m ndt aiops-capacity
python -m ndt aiops-risk --current batfish-snapshots/current --proposed batfish-snapshots/proposed
python -m ndt aiops-replay <timestamp> R1-CORE 203.0.113.1
python -m ndt aiops-train
```

SSH credentials for the scraper are loaded from environment variables via `SSHCredentials.from_env(<profile>)`.

## Architecture

The NDT models a network as three layers that build on each other:

### 1. Topology (schema → loader → devices)

`ndt/topology/schema.py` defines the Pydantic data model. A topology YAML contains a list of `DeviceConfig` objects. Each device has either `vrfs` (Cisco/Juniper) or `vsys` (Palo Alto) — both map to the unified `RoutingInstance` type containing interfaces and routes.

`ndt/topology/loader.py` parses the YAML into a `Topology` object. `ndt/devices/factory.py` converts each `DeviceConfig` into a vendor-specific `Device` subclass (Cisco, Juniper, PaloAlto).

### 2. Device abstraction

`ndt/devices/base.py` — the abstract `Device` class. Key operations:
- `lookup_route(dst_ip, instance)` — longest-prefix match within a VRF/VSys, checking locally-attached subnets first
- `owns_ip(ip)` / `owns_prefix(ip)` — determine if a device owns an IP across all its instances
- `_instances: dict[str, RoutingInstance]` — the per-VRF/VSys routing and interface state

Vendor subclasses (`cisco.py`, `juniper.py`, `palo_alto.py`) implement `vendor_label()` and any vendor-specific behaviour.

### 3. Network graph

`ndt/network/graph.py` — `NetworkGraph` wraps a `networkx.MultiDiGraph`. Nodes are device names; edges are physical links with `enabled` state. Key operations:
- `build(devices)` — walks all device instances and interfaces to construct directed edges
- `disable_link` / `enable_link` — mutates edge `enabled` flags for failure simulation (bidirectional)
- `resolve_nexthop_device(src, next_hop_ip, devices)` — finds which neighbour device owns a next-hop IP

### Path tracer (core MTTD engine)

`ndt/simulation/path_tracer.py` — `trace()` is the primary simulation function. It performs hop-by-hop forwarding:
1. RIB lookup via `device.lookup_route()`
2. Checks egress interface link state in the graph
3. Resolves next-hop IP to a neighbour via `graph.resolve_nexthop_device()`, falling back to `_find_owner()` (full scan across all devices)
4. Detects VRF/VSys transitions and records them in `PathResult.vrf_transitions`
5. Loop detection via a `visited: set[(device, instance)]`; hard cap at `MAX_HOPS = 64`

Returns a `PathResult` with `status` in `{success, blackhole, loop, unreachable}`.

### Integrations

Each integration is self-contained under `ndt/integrations/`:

- **batfish/** — wraps pybatfish to validate config snapshots (`validator.py`) and run differential reachability analysis (`diff.py`). `diff.py` exposes `risk_features()` consumed by the AIOps risk scorer.
- **containerlab/** — `generator.py` converts NDT topology to ContainerLab YAML; `runner.py` shells out to `clab` deploy/destroy.
- **suzieq/** — `poller.py` drives live device polling; `reconcile.py` compares expected topology state (from NDT) against live SuzieQ state to produce a `DriftReport`.
- **aiops/** — ML-based intelligence layer:
  - `baseline.py` / `anomaly.py` — Z-score anomaly detection on SuzieQ parquet data
  - `root_cause.py` — graph-walks the NDT to propagate drift items to a root device
  - `capacity.py` — Prophet-based interface utilisation forecasting
  - `risk_scorer.py` — ML classifier (trained via `models/train.py`, tracked in MLflow) that scores Batfish diff features to produce approve/review/block decisions
  - `replay.py` — reconstructs historical NDT state to re-run the path tracer at a past timestamp

### Scraper

`ndt/scraper/` — async SSH discovery pipeline: `ssh_client.py` (paramiko/asyncssh) → vendor parsers in `parsers/` → `discovery.py` orchestrates concurrent scraping → `reconciler.py` merges results into an existing topology YAML.

### External services (docker-compose)

| Service | Port | Purpose |
|---|---|---|
| Batfish | 9997/9996 | Config analysis; snapshots mounted at `./batfish-snapshots` |
| SuzieQ | 8000 | Live state GUI; data at `./suzieq-data` |
| MLflow | 5000 | Model registry and experiment tracking |

### Data flow

```
Live devices ──SSH──▶ scraper ──▶ topology YAML
                                        │
                         ┌──────────────┴──────────────┐
                         ▼                             ▼
                   NetworkGraph                  Batfish snapshots
                   + Device RIBs                       │
                         │                    batfish-validate/diff
                    path tracer                        │
                    failure sim                   risk_scorer (ML)
                         │
                   SuzieQ poll ──▶ parquet ──▶ anomaly / capacity / RCA
```
