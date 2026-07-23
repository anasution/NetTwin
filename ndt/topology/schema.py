"""Pydantic schema for NDT topology YAML — supports multi-VRF (Cisco/Juniper) and multi-VSys (Palo Alto)."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, field_validator


class ConnectedTo(BaseModel):
    device: str
    interface: str
    vrf: Optional[str] = None
    vsys: Optional[str] = None


class Interface(BaseModel):
    name: str
    ip: str  # CIDR notation e.g. 10.0.0.1/30
    status: str = "up"
    connected_to: Optional[ConnectedTo] = None


class Route(BaseModel):
    prefix: str  # CIDR e.g. 192.168.1.0/24
    next_hop: Optional[str] = None  # None = locally attached
    metric: int = 1
    protocol: str = "static"  # static | ospf | bgp | connected


class RoutingInstance(BaseModel):
    """Represents one VRF (Cisco/Juniper) or one VSys (Palo Alto)."""
    name: str
    interfaces: list[Interface] = []
    routes: list[Route] = []


class DeviceConfig(BaseModel):
    name: str
    type: str  # cisco | juniper | palo_alto
    region: Optional[str] = None
    mgmt_ip: Optional[str] = None
    # Cisco / Juniper use vrfs; Palo Alto uses vsys
    vrfs: Optional[list[RoutingInstance]] = None
    vsys: Optional[list[RoutingInstance]] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"cisco", "juniper", "palo_alto"}
        if v not in allowed:
            raise ValueError(f"device type must be one of {allowed}, got '{v}'")
        return v

    def routing_instances(self) -> list[RoutingInstance]:
        if self.type == "palo_alto":
            return self.vsys or []
        return self.vrfs or []


class Topology(BaseModel):
    devices: list[DeviceConfig]
