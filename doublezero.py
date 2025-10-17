import asyncio
import ipaddress


async def doublezero_is_active() -> bool:
    CMD = "ip link show doublezero0 up".split(" ")
    proc = await asyncio.create_subprocess_exec(
        *CMD, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    return b"UP" in out


async def get_doublezero_routes() -> set[ipaddress.IPv4Address]:
    CMD = "ip route show table main".split(" ")
    proc = await asyncio.create_subprocess_exec(
        *CMD, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    output, _ = await proc.communicate()
    reachable: set[ipaddress.IPv4Address] = set()
    for line in output.decode().splitlines():
        if "dev doublezero0 proto bgp" in line:
            line = line.split(" ")[0]
            reachable.add(ipaddress.IPv4Address(line))
    return reachable
