import asyncio
import ipaddress
import subprocess
from traceback import print_exc
import json
import os
from config import *
# Set sudo command to blank if in systemd (since then we are root)
SUDO = "" if os.geteuid() == 0 else "sudo "

def nft_add_table():
    cmd=f"{SUDO}nft add table inet {NFT_TABLE}"
    subprocess.check_call(cmd.split(" "))
    cmd=f"{SUDO}nft add chain inet {NFT_TABLE} " + r" input { type filter hook input priority 0 \; }"
    subprocess.check_call(cmd, shell=True)

def nft_drop_table():
    cmd=f"{SUDO}nft delete table inet {NFT_TABLE}"
    subprocess.call(cmd.split(" "))

def get_nft_counters()->dict[ipaddress.IPv4Address, int]:
    cmd=f"{SUDO}nft -j list chain inet {NFT_TABLE} input"
    counters:dict[ipaddress.IPv4Address, int] = {}
    try:
        (_status, output) = subprocess.getstatusoutput(cmd)
        x = json.loads(output)
        for row in x['nftables']:
            if 'rule' not in row:
                continue
            expr = row['rule']['expr']
            source = ipaddress.IPv4Address(expr[0]['match']['right'])
            counters[source] = expr[1]['counter']['packets']
    except:
        print_exc()
    finally:
        return counters

def nft_add_counter(ip:ipaddress.IPv4Address):
    cmd = f"{SUDO} nft add rule inet {NFT_TABLE} input ip saddr {ip} counter"
    (_status, _output) = subprocess.getstatusoutput(cmd)

async def get_staked_nodes() ->dict[str, int]:
    cmd = f"-u{CLUSTER} validators --output json"
    proc = await asyncio.create_subprocess_exec("solana", *cmd.split(" "), stdout=asyncio.subprocess.PIPE,
           stderr=asyncio.subprocess.PIPE)
    stdout, _stderr = await proc.communicate()
    output = json.loads(stdout)
    return {v['identityPubkey']:v['activatedStake'] for v in output["validators"]  if v['activatedStake'] > MIN_STAKE_TO_CARE and not v['delinquent']}

async def get_contact_infos()->dict[str, ipaddress.IPv4Address]:
    cmd = f"-u{CLUSTER} gossip --output json"
    proc = await asyncio.create_subprocess_exec("solana", *cmd.split(" "), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _stderr = await proc.communicate()
    output = json.loads(stdout)
    return  {v['identityPubkey']:ipaddress.IPv4Address( v['ipAddress']) for v in output if 'tpuPort' in v}

def kill_dz_interface()->None:
    subprocess.call(f"{SUDO} ip link set doublezero0 down", shell=True)
