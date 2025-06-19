#!/usr/bin/python3
from collections import deque
import subprocess
import json
import ipaddress
import asyncio
import dataclasses
from traceback import print_exc
import socket
import ping
import time
from doublezero import doublezero_is_active


def get_config()->list['Connection']:
    connections = [
        Connection(name="Public Internet", ip_address=get_default_ip()),
        DoubleZeroConnection(name="DoubleZero", ip_address=get_default_ip(), use_active_monitoring=True, preference=100)
    ]
    return connections

# Table to create in nftables
NFT_TABLE = "dz_mon"
# Which cluster to connect to (fed to solana CLI)
CLUSTER="mainnet-beta"

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

def get_default_ip()-> ipaddress.IPv4Address:
    # Doesn't actually connect — just figures out the outbound IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))  # Google DNS
    ip = ipaddress.IPv4Address(s.getsockname()[0])
    s.close()
    return ip

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

@dataclasses.dataclass
class Connection:
    name:str
    ip_address: ipaddress.IPv4Address
    use_active_monitoring: bool = False
    preference: int = 0
    health_records: deque[HealthRecord] = dataclasses.field(default_factory=lambda : deque(maxlen=100))

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
    use_active_monitoring: bool = True

    async def self_check(self) -> bool:
        return await doublezero_is_active()


class Monitor:
    staked_nodes:dict[str, StakedNode] = {}
    connection: Connection
    connections: list[Connection]
    decision_check_interval_seconds: float = 1.0
    passive_monitoring_interval_seconds: float = 1.0
    active_monitoring_interval_seconds: float = 10.0
    # how long do we wait before consindering connection dead
    grace_period_sec: float = 2.0
    # how long do we wait before switching back to a connection that was not used
    caution_period_sec: float = 60.0
    # how much stake do we need to observe to consider connection "good"
    stake_threshold: float = 0.9
    # how long time to keep a particular connection after switch is made
    switch_debounce_seconds: float = 60.0
    # Interval between refreshes of gossip tables via RPC
    node_refresh_interval_seconds: float = 60.0

    def __init__(self, connections: list[Connection]) -> None:
        self.connections = connections
        print(f"Starting monitoring with connections: {connections}")
        self.connection = connections[0]

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
            counters = get_nft_counters()
            reachable_stake = 0
            unreachable_stake = 0
            for pk, node in self.staked_nodes.items():
                cnt = counters.get(node.ip_address,0)
                diff = cnt - node.packet_count
                node.packet_count = cnt
                if diff > 0:
                    reachable_stake += node.stake / LAMPORTS_PER_SOL
                else:
                    unreachable_stake += node.stake / LAMPORTS_PER_SOL
            rec = HealthRecord(reachable_stake_fraction=reachable_stake/(1+reachable_stake+unreachable_stake))
            print(f"Passive monitoring of {self.connection.name}: reachable stake {reachable_stake}, unreachable stake: {unreachable_stake} (quality={rec.reachable_stake_fraction:.1%})")
            self.connection.health_records.append(rec)
            await asyncio.sleep(self.passive_monitoring_interval_seconds)

    async def main(self)->None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.refresh_staked_nodes())
            tg.create_task(self.passive_monitoring())
            tg.create_task(self.active_monitoring())
            tg.create_task(self.decision())

    async def decision(self)->None:
        """
        Goes over the connections ensuring we are using the "best" one.
        """
        # sleep before truly starting this task so we have data to work with
        await asyncio.sleep(self.caution_period_sec)
        while True:
            #live_connections:list[tuple[float, Connection]] = []
            live_connections:list[Connection] = []

            for conn in self.connections:
                # check for obvious issues
                if not await conn.self_check():
                    continue

                if self.connection == conn:
                    # check if we can still reach target % of stake
                    if conn.get_best_in_period(self.grace_period_sec) > self.stake_threshold:
                        #quality = conn.mean_in_period(self.caution_period_sec)
                        live_connections.append(conn)
                else:
                    if conn.get_worst_in_period(self.caution_period_sec) > self.stake_threshold:
                        #quality = conn.mean_in_period(self.caution_period_sec)
                        live_connections.append(conn)

            live_connections.sort(key=lambda c: c.preference)
            if self.connection != live_connections[-1]:
                self.connection = live_connections[-1]
                print(f"Switching to preferred connection {self.connection.name}")
                #TODO: emit signal as appropriate
                await asyncio.sleep(self.switch_debounce_seconds)
            elif self.connection not in live_connections:
                print("Current connection is DEAD")
                if not live_connections:
                    if self.connection != self.connections[0]:
                        print("No connections are good, switching to default")
                        self.connection = self.connections[0]
                        #TODO: emit signal as appropriate
                        await asyncio.sleep(self.switch_debounce_seconds)
                else:
                    self.connection = live_connections[-1]
                    print(f"Switching to {self.connection.name}")
                    #TODO: emit signal as appropriate
                    await asyncio.sleep(self.switch_debounce_seconds)

            await asyncio.sleep(self.decision_check_interval_seconds)


    async def active_monitoring(self)->None:
        """
            Monitor connection quality by actively pinging hosts
            This is needed when connection is not active and no traffic can be expected
        """
        while True:
            for conn in self.connections:
                if not conn.use_active_monitoring:
                    continue
                # If the connection is in use, we can rely on passive monitoring
                if self.connection == conn:
                    continue

                tasks = []
                stakes = []
                for v in self.staked_nodes.values():
                    tasks.append(ping.ping(bind=conn.ip_address, host=v.ip_address))
                    stakes.append(v.stake)

                # TODO: cascade these properly
                ping_results = await asyncio.gather(*tasks)
                reachable_stake = 0
                unreachable_stake = 0
                for (pr, stake) in zip(ping_results, stakes):
                    if pr:
                        reachable_stake += stake / LAMPORTS_PER_SOL
                    else:
                        unreachable_stake += stake / LAMPORTS_PER_SOL

                rec = HealthRecord(reachable_stake_fraction=reachable_stake/(1+reachable_stake+unreachable_stake))
                print(f"Active monitoring of {conn.name}: reachable stake {reachable_stake}, unreachable stake: {unreachable_stake} (quality={rec.reachable_stake_fraction:.1%})")
                conn.health_records.append(rec)

            await asyncio.sleep(self.active_monitoring_interval_seconds)

if __name__=="__main__":
    connections = get_config()
    with Monitor(connections) as mon:
        asyncio.run(mon.main())
