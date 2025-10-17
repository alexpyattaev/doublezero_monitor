import asyncio
import ipaddress
import subprocess
from traceback import print_exc
import json
import os
from typing import Any
from config import *
from urllib import request

# Set sudo command to blank if in systemd (since then we are root)
SUDO = "" if os.geteuid() == 0 else "sudo "


def nft_add_table():
    cmd = f"{SUDO}nft add table inet {NFT_TABLE}"
    _ = subprocess.check_call(cmd.split(" "))
    cmd = (
        f"{SUDO}nft add chain inet {NFT_TABLE} "
        + r" input { type filter hook input priority 0 \; }"
    )
    _ = subprocess.check_call(cmd, shell=True)


def nft_drop_table():
    cmd = f"{SUDO}nft delete table inet {NFT_TABLE}"
    _ = subprocess.call(cmd.split(" "))


def get_nft_counters() -> dict[ipaddress.IPv4Address, int]:
    cmd = f"{SUDO}nft -j list chain inet {NFT_TABLE} input"
    counters: dict[ipaddress.IPv4Address, int] = {}
    try:
        (_status, output) = subprocess.getstatusoutput(cmd)
        x = json.loads(output)
        for row in x["nftables"]:
            if "rule" not in row:
                continue
            expr = row["rule"]["expr"]
            source = ipaddress.IPv4Address(expr[0]["match"]["right"])
            counters[source] = expr[1]["counter"]["packets"]
    except:
        print_exc()
    finally:
        return counters


def nft_add_counter(ip: ipaddress.IPv4Address):
    cmd = f"{SUDO} nft add rule inet {NFT_TABLE} input ip saddr {ip} counter"
    (_status, _output) = subprocess.getstatusoutput(cmd)


async def get_staked_nodes() -> dict[str, int]:
    output = await get_from_RPC("getVoteAccounts")
    return {
        v["nodePubkey"]: v["activatedStake"]
        for v in output["current"]
        if v["activatedStake"] > MIN_STAKE_TO_CARE
    }


async def get_contact_infos() -> dict[str, ipaddress.IPv4Address]:
    output = await get_from_RPC("getClusterNodes")
    return {
        v["pubkey"]: ipaddress.IPv4Address(v["tpuQuic"].split(":")[0])
        for v in output
        if v.get("tpuQuic") is not None
    }


def kill_dz_interface() -> None:
    _ = subprocess.call(f"{SUDO}ip link set doublezero0 down", shell=True)


async def get_from_RPC(method: str) -> Any:
    url = f"https://api.{CLUSTER}.solana.com"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": [],
        }
    ).encode()

    loop = asyncio.get_event_loop()

    def fetch() -> dict[str, Any]:
        req = request.Request(url, data=data, headers=headers, method="POST")
        with request.urlopen(req) as resp:
            return json.load(resp)

    try:
        result = await loop.run_in_executor(None, fetch)
        return result["result"]
    except Exception as e:
        print(f"Could not fetch data from RPC, error {e}")
        return []
