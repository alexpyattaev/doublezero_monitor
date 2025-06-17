#!/usr/bin/python3
import subprocess
import json
import ipaddress
import asyncio
import dataclasses
from traceback import print_exc

NFT_TABLE = "dz_mon"
CLUSTER="mainnet-beta"
LAMPORTS_PER_SOL = 1000000000
MIN_STAKE_TO_CARE = LAMPORTS_PER_SOL * 10000

def nft_add_table():
    CMD=f"sudo nft add table inet {NFT_TABLE}"
    subprocess.check_call(CMD.split(" "))
    CMD=f"sudo nft add chain inet {NFT_TABLE} " + r" input { type filter hook input priority 0 \; }"
    subprocess.check_call(CMD, shell=True)

def nft_drop_table():
    CMD=f"sudo nft delete table inet {NFT_TABLE}"
    subprocess.call(CMD.split(" "))

def get_nft_counters()->dict[ipaddress.IPv4Address, int]:
    CMD=f"sudo nft -j list chain inet {NFT_TABLE} input"
    counters = {}
    try:
        (status, output) = subprocess.getstatusoutput(CMD)
        x = json.loads(output)
        for row in x['nftables']:
            if 'rule' not in row:
                continue
            expr = row['rule']['expr']
            source = ipaddress.ip_address(expr[0]['match']['right'])
            counter =expr[1]['counter']['packets']
            counters[source] = counter
    except:
        print_exc()
    finally:
        return counters

def nft_add_counter(ip:ipaddress.IPv4Address):
    CMD = f"sudo nft add rule inet {NFT_TABLE} input ip saddr {ip} counter"
    (status, output) = subprocess.getstatusoutput(CMD)

def nft_reset_counters():
    CMD = f"sudo nft reset counters table inet {NFT_TABLE}"
    (status, output) = subprocess.getstatusoutput(CMD)


def doublezero_is_active()->bool:
    CMD="doublezero status"
    (status, output)= subprocess.getstatusoutput(CMD)
    return status == 0

def get_doublezero_routes()->set[ipaddress.IPv4Address]:
    CMD = "ip route show table main"
    (status, output) = subprocess.getstatusoutput(CMD)
    reachable = set()
    for line in output.splitlines():
        if 'doublezero0' in line:
            reachable.add(ipaddress.ip_address(line.split(' ')[0]))
    return reachable

async def get_staked_nodes():
    CMD = f"-u{CLUSTER} validators --output json"
    proc = await asyncio.create_subprocess_exec("solana", *CMD.split(" "), stdout=asyncio.subprocess.PIPE,
           stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    output = json.loads(stdout)
    return {v['identityPubkey']:v['activatedStake'] for v in output["validators"]  if v['activatedStake'] > MIN_STAKE_TO_CARE and not v['delinquent']}

async def get_contact_infos():
    CMD = f"-u{CLUSTER} gossip --output json"
    proc = await asyncio.create_subprocess_exec("solana", *CMD.split(" "), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    output = json.loads(stdout)
    return  {v['identityPubkey']:ipaddress.ip_address( v['ipAddress']) for v in output if 'tpuPort' in v}

@dataclasses.dataclass
class StakedNode:
    pubkey:str
    ip_address: ipaddress.IPv4Address
    stake: int

class Monitor:
    staked_nodes = {}
    contact_infos = {}

    def __init__(self) -> None:
        pass

    def __enter__(self):
        print("Setting up nftables")
        nft_add_table()
        return self

    def __exit__(self,exc_type, exc_value, traceback):
        print("Cleaning up")
        nft_drop_table()


    async def refresh_staked_nodes(self):
        while True:
            n = 0
            print("Refreshing staked nodes")
            self.contact_infos = await get_contact_infos()
            new_staked = await get_staked_nodes()

            new_nodes = set(new_staked) - set(self.staked_nodes)
            # do not add too many conuters all at once
            while len(new_nodes) > 10:
                new_nodes.pop()

            for pk in new_nodes:
                ip = self.contact_infos[pk]
                self.staked_nodes[pk] = StakedNode(stake = new_staked[pk],
                    ip_address=ip,
                    pubkey=pk,
                )
                n+=1
                print(f"Add counter for {ip}")
                nft_add_counter(ip)
            print(f"Added {n} counters")
            await asyncio.sleep(300)


    async def check_counters(self)->None:
        while True:
            counters = get_nft_counters()
            reachable_stake = 0
            unreachable_stake = 0
            for pk, node in self.staked_nodes.items():
                cnt = counters.get(node.ip_address,0)
                if cnt > 0:
                    reachable_stake += node.stake / LAMPORTS_PER_SOL
                else:
                    unreachable_stake += node.stake / LAMPORTS_PER_SOL
            print(f"Passive monitoring: reachable stake {reachable_stake}, unreachable stake: {unreachable_stake}")
            nft_reset_counters()
            await asyncio.sleep(10)

    async def main(self)->None:
        async with asyncio.TaskGroup() as tg:
            task1 = tg.create_task(self.refresh_staked_nodes())
            task2 = tg.create_task(self.check_counters())
            task3 = tg.create_task(self.active_monitoring())


    # Monitor DZ connection quality by actively pinging hosts
    # This is needed when DZ is not active and no traffic can be expected
    async def active_monitoring(self)->None:
        while True:
            #print("Actively pinging DZ nodes")
            #TODO: implement this
            await asyncio.sleep(32)



if __name__=="__main__":
    with Monitor() as mon:
        asyncio.run(mon.main())
