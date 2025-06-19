import asyncio
import ipaddress

async def ping(bind:ipaddress.IPv4Address, host: ipaddress.IPv4Address, count: int = 1)->bool:
    """
    Runs a ping to the specified node and returns True if reply is received
    """
    args = f'ping -c1 -q -W0.5 -n{count} -I{bind} {host}'.split(' ')

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )

    await proc.wait()
    return proc.returncode != 0
