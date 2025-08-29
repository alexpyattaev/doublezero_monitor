#!/usr/bin/python3
from collections import deque
import subprocess
import json
import ipaddress
import asyncio
import dataclasses
from traceback import print_exc
import time
from doublezero import doublezero_is_active, get_doublezero_routes
import task_group

# Table to create in nftables
NFT_TABLE = "dz_mon"
# Which cluster to connect to (fed to solana CLI)
CLUSTER="testnet"

# how much stake do we need to observe to consider connection "good"
STAKE_THRESHOLD: float = 0.9

# Path to the admin RPC socket of the validator
ADMIN_RPC_PATH="/home/sol/ledger/admin.rpc"

LAMPORTS_PER_SOL = 1000000000
# Minimal stake of node for us to care about it
# Setting this higher reduces overheads of monitoring
MIN_STAKE_TO_CARE = LAMPORTS_PER_SOL * 100000



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
            source = ipaddress.IPv4Address(expr[0]['match']['right'])
            counter =expr[1]['counter']['packets']
            counters[source] = counter
    except:
        print_exc()
    finally:
        return counters

def nft_add_counter(ip:ipaddress.IPv4Address):
    CMD = f"sudo nft add rule inet {NFT_TABLE} input ip saddr {ip} counter"
    (status, output) = subprocess.getstatusoutput(CMD)

async def get_staked_nodes():
    CMD = f"-u{CLUSTER} validators --output json"
    proc = await asyncio.create_subprocess_exec("solana", *CMD.split(" "), stdout=asyncio.subprocess.PIPE,
           stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    output = json.loads(stdout)
    return {v['identityPubkey']:v['activatedStake'] for v in output["validators"]  if v['activatedStake'] > MIN_STAKE_TO_CARE and not v['delinquent']}

async def get_contact_infos()->dict[str, ipaddress.IPv4Address]:
    CMD = f"-u{CLUSTER} gossip --output json"
    proc = await asyncio.create_subprocess_exec("solana", *CMD.split(" "), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    output = json.loads(stdout)
    return  {v['identityPubkey']:ipaddress.IPv4Address( v['ipAddress']) for v in output if 'tpuPort' in v}

@dataclasses.dataclass
class StakedNode:
    pubkey:str
    ip_address: ipaddress.IPv4Address
    stake: int
    packet_count: int

@dataclasses.dataclass
class HealthRecord:
    reachable_stake_fraction: float
    timestamp: float = dataclasses.field(default_factory=time.time)

    def __str__(self) -> str:
        return f"({self.reachable_stake_fraction*100}% at {self.timestamp})"

    def __repr__(self) -> str:
        return f"({self.reachable_stake_fraction*100}% at {self.timestamp})"

@dataclasses.dataclass
class Connection:
    name:str
    reachable_ips: set[ipaddress.IPv4Address] = dataclasses.field(default_factory=set)
    health_records: deque[HealthRecord] = dataclasses.field(default_factory=lambda : deque(maxlen=100))

    async def update_reachable_nodes(self):
        return

    def is_reachable(self, ip:ipaddress.IPv4Address)->bool:
        return True

    async def self_check(self)->bool:
        return True

    def get_best_in_period(self, grace_period:float)->float:
        now = time.time()
        best_in_grace_period = 0.0
        for rec in self.health_records:
            age = now - rec.timestamp
            if age < grace_period:
                best_in_grace_period = max(best_in_grace_period, rec.reachable_stake_fraction)
        return best_in_grace_period

    def mean_in_period(self, period:float)->float:
        now = time.time()
        records = []
        for rec in self.health_records:
            age = now - rec.timestamp
            if age< period:
                records.append(rec.reachable_stake_fraction)
        if not records:
            return 0.0
        return sum(records)/ len(records)

    def get_worst_in_period(self, caution_period: float)->float:
        now = time.time()
        worst_in_caution_period = None
        for rec in self.health_records:
            age = now - rec.timestamp
            if age < caution_period:
                worst_in_caution_period = min(worst_in_caution_period, rec.reachable_stake_fraction) if worst_in_caution_period is not None else rec.reachable_stake_fraction
        return 0.0 if worst_in_caution_period is None else worst_in_caution_period

@dataclasses.dataclass
class DoubleZeroConnection(Connection):
    async def self_check(self) -> bool:
        status = await doublezero_is_active()
        if not status:
            self.reachable_ips.clear()
        return status

    async def update_reachable_nodes(self):
        if not await doublezero_is_active():
            self.reachable_ips.clear()
        else:
            self.reachable_ips = await get_doublezero_routes()

    def is_reachable(self, ip:ipaddress.IPv4Address) -> bool:
        return ip in self.reachable_ips

class Monitor:
    staked_nodes:dict[str, StakedNode] = {}
    connection_dz: Connection
    decision_check_interval_seconds: float = 1.0
    passive_monitoring_interval_seconds: float = 1.0
    # how long do we wait before consindering connection dead
    grace_period_sec: float = 2.0
    # how long do we wait before switching back to a connection that was not used
    caution_period_sec: float = 60.0
    # how long time to keep a particular connection after switch is made
    switch_debounce_seconds: float = 60.0
    # Interval between refreshes of gossip tables via RPC
    node_refresh_interval_seconds: float = 60.0

    def __init__(self) -> None:
        self.connection_dz = DoubleZeroConnection(name="DoubleZero")

    def __enter__(self):
        print("Setting up nftables")
        nft_add_table()
        return self

    def __exit__(self,exc_type, exc_value, traceback):
        print("Cleaning up")
        nft_drop_table()

    async def refresh_staked_nodes(self):
        """
        Refresh list of staked nodes, update NFT counters accordingly
        """
        while True:
            n = 0
            print("Refreshing staked nodes")
            contact_infos = await get_contact_infos()
            new_staked = await get_staked_nodes()

            await self.connection_dz.update_reachable_nodes()

            new_nodes = set(new_staked) - set(self.staked_nodes)
            to_remove_nodes = set(self.staked_nodes) -  set(new_staked)
            for pk in to_remove_nodes:
                print(f"Removing node {pk} from monitored set")
                self.staked_nodes.pop(pk)
                # TODO: use to_remove_nodes to clean out dead counters in nftables
                # may need named counters for that

            # do not add too many conuters all at once to avoid blocking event loop
            while len(new_nodes) > 10:
                new_nodes.pop()

            for pk in new_nodes:
                ip = contact_infos[pk]
                self.staked_nodes[pk] = StakedNode(stake = new_staked[pk],
                    ip_address=ip,
                    pubkey=pk,
                    packet_count = 0,
                )
                n+=1
                print(f"Add counter for {ip}")
                nft_add_counter(ip)
            print(f"Added {n} counters")
            await asyncio.sleep(self.node_refresh_interval_seconds)


    async def passive_monitoring(self)->None:
        """
        Check NFT counters for incoming traffic on active connections to check their health
        """
        while True:
            await asyncio.sleep(self.passive_monitoring_interval_seconds)
            counters = get_nft_counters()
            reachable_stake = 0.0
            unreachable_stake = 0.0
            for _pk, node in self.staked_nodes.items():
                cnt = counters.get(node.ip_address,0)
                diff = cnt - node.packet_count
                node.packet_count = cnt
                if not self.connection_dz.is_reachable(node.ip_address):
                    continue
                if diff > 0:
                    reachable_stake += node.stake / LAMPORTS_PER_SOL
                else:
                    unreachable_stake += node.stake / LAMPORTS_PER_SOL
            if unreachable_stake == unreachable_stake == 0:
                print("No stake from DZ captured in counters...")
                continue
            rec = HealthRecord(reachable_stake_fraction=reachable_stake/(1+reachable_stake+unreachable_stake))
            print(f"Passive monitoring of {self.connection_dz.name}: reachable stake {reachable_stake}, unreachable stake: {unreachable_stake} (quality={rec.reachable_stake_fraction:.1%})")
            self.connection_dz.health_records.append(rec)

    async def main(self)->None:
        async with task_group.TaskGroup() as tg:
            tg.create_task(self.refresh_staked_nodes())
            tg.create_task(self.passive_monitoring())
            tg.create_task(self.decision())

    async def decision(self)->None:
        """
        Goes over the connections ensuring we are using the "best" one.
        """
        # sleep before truly starting this task so we have data to work with
        await asyncio.sleep(self.caution_period_sec)
        while True:
            await asyncio.sleep(self.decision_check_interval_seconds)

            # check for obvious issues
            if not await self.connection_dz.self_check():
                print("DZ already disabled")
                continue

            # check if we can still reach target % of stake
            if self.connection_dz.get_best_in_period(self.grace_period_sec) < STAKE_THRESHOLD:
                print("Failure condition detected: Disconnecting DZ")
                subprocess.call("doublezero disconnect", shell=True)
                print(self.connection_dz.health_records)
                exit(1)

if __name__=="__main__":
    with Monitor() as mon:
        asyncio.run(mon.main())
