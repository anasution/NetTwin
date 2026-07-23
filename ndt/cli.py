"""Network Digital Twin — CLI entry point.

Usage:
    python -m ndt <command> [options]

All package installation must be done inside WSL Ubuntu-24.04 virtualenv (~/ndt-env).
"""
from __future__ import annotations
import sys
import json
import logging
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()
log = logging.getLogger("ndt.cli")


def _state_file(topology: str) -> Path:
    return Path(topology).with_suffix(".link_state.json")


def _load_link_state(topology: str) -> list[list[str]]:
    sf = _state_file(topology)
    if sf.exists():
        return json.loads(sf.read_text()).get("disabled", [])
    return []


def _save_link_state(topology: str, disabled: list[list[str]]) -> None:
    _state_file(topology).write_text(json.dumps({"disabled": disabled}, indent=2))


def _load(topology: str):
    from ndt.topology.loader import load
    from ndt.devices.factory import build_devices
    from ndt.network.graph import NetworkGraph

    topo = load(topology)
    devices = build_devices(topo.devices)
    graph = NetworkGraph()
    graph.build(devices)
    # Apply persisted link failures
    for pair in _load_link_state(topology):
        if len(pair) == 2:
            graph.disable_link(pair[0], pair[1])
            graph.disable_link(pair[1], pair[0])
    return topo, devices, graph


# ─── Root group ──────────────────────────────────────────────────────────────

@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
def cli(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


# ─── Topology / Simulation ───────────────────────────────────────────────────

@cli.command("load")
@click.argument("topology", default="topology/example.yaml")
def cmd_load(topology: str):
    """Load and validate topology YAML."""
    topo, devices, graph = _load(topology)
    link_count = graph.graph.number_of_edges()
    console.print(f"[bold green]Topology loaded[/bold green]: {topology}")
    console.print(f"  Devices : {len(topo.devices)}")
    console.print(f"  Links   : {link_count}")

    t = Table("Device", "Type", "Instances", "Routes", box=box.SIMPLE)
    for d in topo.devices:
        instances = d.routing_instances()
        route_count = sum(len(ri.routes) for ri in instances)
        t.add_row(d.name, d.type, str(len(instances)), str(route_count))
    console.print(t)


@cli.command("trace")
@click.argument("src_device")
@click.argument("dst_ip")
@click.option("--vrf", default="default", show_default=True)
@click.option("--vsys", default=None)
@click.option("--topology", default="topology/example.yaml", show_default=True)
def cmd_trace(src_device: str, dst_ip: str, vrf: str, vsys: Optional[str], topology: str):
    """Trace a forwarding path through the NDT."""
    from ndt.simulation.path_tracer import trace

    _, devices, graph = _load(topology)
    instance = vsys if vsys else vrf
    result = trace(src_device, dst_ip, devices, graph, src_instance=instance)

    status_color = {"success": "green", "blackhole": "red", "loop": "yellow", "unreachable": "red"}.get(
        result.status, "white"
    )
    console.print(f"\n[bold {status_color}]Path: {result.path_str}[/bold {status_color}]")
    console.print(f"Status : [{status_color}]{result.status}[/{status_color}]")
    if result.reason:
        console.print(f"Reason : {result.reason}")
    if result.vrf_transitions:
        console.print(f"VRF transitions: {' → '.join(result.vrf_transitions)}")

    t = Table("#", "Device", "VRF/VSys", "Interface", "Next-hop", box=box.SIMPLE)
    for i, hop in enumerate(result.hops, 1):
        t.add_row(str(i), hop.device, hop.instance, hop.outgoing_interface or "—", hop.next_hop_ip or "LOCAL")
    console.print(t)


@cli.command("devices")
@click.option("--topology", default="topology/example.yaml", show_default=True)
@click.option("--vrf", default=None)
def cmd_devices(topology: str, vrf: Optional[str]):
    """List all devices and their routing instances."""
    _, devices, _ = _load(topology)
    t = Table("Device", "Type", "Instance", "Interfaces", box=box.SIMPLE)
    for name, dev in devices.items():
        for inst_name in dev.instance_names():
            if vrf and inst_name != vrf:
                continue
            ri = dev._instances[inst_name]
            ifaces = ", ".join(i.name for i in ri.interfaces[:3])
            if len(ri.interfaces) > 3:
                ifaces += f" +{len(ri.interfaces)-3}"
            t.add_row(name, dev.device_type, inst_name, ifaces or "—")
    console.print(t)


@cli.command("fail-link")
@click.argument("device_a")
@click.argument("device_b")
@click.option("--topology", default="topology/example.yaml", show_default=True)
def cmd_fail_link(device_a: str, device_b: str, topology: str):
    """Disable a link to simulate failure (persists across commands)."""
    from ndt.simulation.failure import fail_link
    _, devices, graph = _load(topology)
    fail_link(graph, device_a, device_b)
    # Persist the failure so subsequent trace commands see it
    disabled = _load_link_state(topology)
    pair = sorted([device_a, device_b])
    if pair not in disabled:
        disabled.append(pair)
    _save_link_state(topology, disabled)
    console.print(f"[red]Link disabled[/red]: {device_a} ↔ {device_b}")


@cli.command("restore-link")
@click.argument("device_a")
@click.argument("device_b")
@click.option("--topology", default="topology/example.yaml", show_default=True)
def cmd_restore_link(device_a: str, device_b: str, topology: str):
    """Re-enable a previously disabled link."""
    from ndt.simulation.failure import restore_link
    _, devices, graph = _load(topology)
    restore_link(graph, device_a, device_b)
    # Remove from persisted state
    pair = sorted([device_a, device_b])
    disabled = [p for p in _load_link_state(topology) if p != pair]
    _save_link_state(topology, disabled)
    console.print(f"[green]Link restored[/green]: {device_a} ↔ {device_b}")


# ─── Scraper ─────────────────────────────────────────────────────────────────

@cli.command("scrape")
@click.option("--inventory", required=True, help="Device inventory CSV")
@click.option("--output", required=True, help="Output topology YAML path")
@click.option("--merge", default=None, help="Existing topology YAML to merge into")
@click.option("--max-concurrent", default=50, show_default=True)
@click.option("--region", default=None, help="Only scrape devices in this region")
@click.option("--by-region", is_flag=True, default=False,
              help="Shard inventory by region and run regional scrapers in parallel")
def cmd_scrape(inventory: str, output: str, merge: Optional[str], max_concurrent: int,
               region: Optional[str], by_region: bool):
    """SSH to all devices and auto-generate topology YAML.

    Use --by-region for ISP-scale fleets (5000+ devices): each region runs its
    own SSH pool concurrently so wall-clock time = slowest region, not sum of all.
    Use --region <name> to scrape a single region for incremental updates.
    """
    import csv
    from ndt.scraper.discovery import discover_topology, discover_by_region, load_inventory
    from ndt.scraper.reconciler import reconcile
    from ndt.scraper.ssh_client import SSHCredentials

    rows = load_inventory(inventory)
    creds_profile = rows[0].get("credentials_profile", "default") if rows else "default"
    creds = SSHCredentials.from_env(creds_profile)

    if by_region:
        regions = sorted({r.get("region", "_global") for r in rows})
        console.print(f"[bold]Regional scrape[/bold]: {len(rows)} devices across {len(regions)} regions")
        for r in regions:
            count = sum(1 for row in rows if (row.get("region") or "_global") == r)
            console.print(f"  {r}: {count} devices")
        with console.status("Running regional discovery…"):
            parsed, failures = discover_by_region(rows, creds, max_concurrent_per_region=max_concurrent)
    else:
        target_count = sum(1 for r in rows if region is None or r.get("region") == region)
        label = f"region={region}" if region else "all regions"
        console.print(f"[bold]Scraping {target_count} devices[/bold] ({label}, max {max_concurrent} concurrent)…")
        with console.status("Running discovery…"):
            parsed, failures = discover_topology(rows, creds, max_concurrent, region=region)

    console.print(f"[green]Success[/green]: {len(parsed)} devices  [red]Failed[/red]: {len(failures)}")
    if failures:
        for host, err in list(failures.items())[:5]:
            console.print(f"  {host}: {err}")

    reconcile(merge, parsed, output)
    console.print(f"[bold green]Topology written[/bold green]: {output}")


# ─── AIOps ───────────────────────────────────────────────────────────────────

@cli.command("aiops-anomaly")
@click.option("--data-dir", default="suzieq-data", show_default=True)
@click.option("--baseline-window", default=14, show_default=True, help="Days for baseline")
def cmd_aiops_anomaly(data_dir: str, baseline_window: int):
    """Run anomaly detection against latest SuzieQ poll."""
    from ndt.integrations.aiops.baseline import load_baseline
    from ndt.integrations.aiops.anomaly import run_anomaly_detection
    import pandas as pd

    baselines = load_baseline("route_count")
    route_df = _try_load_parquet(data_dir, "routes")
    iface_df = _try_load_parquet(data_dir, "interfaces")
    bgp_df = _try_load_parquet(data_dir, "bgp")

    report = run_anomaly_detection(route_df, iface_df, bgp_df, baselines)

    console.print(f"\n[bold]Anomaly Report[/bold]: {len(report.events)} events ({len(report.critical)} critical)")
    if report.ok:
        console.print("[green]No anomalies detected[/green]")
        return

    t = Table("Device", "Instance", "Metric", "Value", "Z-score", "Severity", "Description", box=box.SIMPLE)
    for e in report.events:
        color = {"critical": "red", "medium": "yellow", "low": "white"}[e.severity]
        t.add_row(e.device, e.instance, e.metric, f"{e.current_value:.1f}",
                  f"{e.zscore:.1f}", f"[{color}]{e.severity}[/{color}]", e.description[:60])
    console.print(t)


@cli.command("aiops-train")
@click.option("--data-dir", default="aiops-data", show_default=True)
def cmd_aiops_train(data_dir: str):
    """Train/retrain ML risk scorer."""
    from ndt.integrations.aiops.models.train import train_risk_model

    console.print("Training risk model…")
    model = train_risk_model(use_synthetic=True)
    console.print("[green]Model trained and saved[/green]")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _try_load_parquet(data_dir: str, table: str):
    import pandas as pd
    p = Path(data_dir) / f"{table}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame()


if __name__ == "__main__":
    cli()
