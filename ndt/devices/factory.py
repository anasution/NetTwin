"""Build the right Device subclass from a DeviceConfig."""
from ndt.topology.schema import DeviceConfig
from ndt.devices.base import Device
from ndt.devices.cisco import CiscoDevice
from ndt.devices.juniper import JuniperDevice
from ndt.devices.palo_alto import PaloAltoDevice

_MAP = {
    "cisco": CiscoDevice,
    "juniper": JuniperDevice,
    "palo_alto": PaloAltoDevice,
}


def build_device(config: DeviceConfig) -> Device:
    cls = _MAP.get(config.type)
    if cls is None:
        raise ValueError(f"Unknown device type: {config.type}")
    return cls(config)


def build_devices(configs: list[DeviceConfig]) -> dict[str, Device]:
    return {d.name: build_device(d) for d in configs}
