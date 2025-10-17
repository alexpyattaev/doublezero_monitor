#!/usr/bin/python3
from collections import defaultdict, deque
from doublezero import doublezero_is_active, get_doublezero_routes
import asyncio
import dataclasses
import ipaddress
import task_group
import time
from config import *
from helpers import *


@dataclasses.dataclass
class StakedNode:
    pubkey: str
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
class DZConnection:
    reachable_ips: set[ipaddress.IPv4Address] = dataclasses.field(default_factory=set)
    health_records: deque[HealthRecord] = dataclasses.field(
        default_factory=lambda: deque(maxlen=100)
    )

    def get_best_in_period(self, grace_period_seconds: float) -> float:
        """Returns best quality observed in provided period, and 0
        if no observations were made."""
        now = time.time()
        best_in_grace_period = 0.0
        for rec in self.health_records:
            age = now - rec.timestamp
            if age < grace_period_seconds:
                best_in_grace_period = max(
                    best_in_grace_period, rec.reachable_stake_fraction
                )
        return best_in_grace_period

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

    def is_reachable(self, ip: ipaddress.IPv4Address) -> bool:
        return ip in self.reachable_ips


class Monitor:
    staked_nodes: dict[str, StakedNode] = {}
    connection: DZConnection

    def __init__(self) -> None:
        self.connection = DZConnection()

    def __enter__(self):
        print("Setting up nftables")
        nft_add_table()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        print("Cleaning up")
        nft_drop_table()

    async def refresh_staked_nodes(self):
        """
        Refresh list of staked nodes, update NFT counters accordingly
        """
        while True:
            print("Refreshing staked nodes")
            contact_infos = await get_contact_infos()
            new_staked = await get_staked_nodes()

            await self.connection.update_reachable_nodes()

            new_nodes = set(new_staked) - set(self.staked_nodes)
            for pk in new_nodes.copy():
                ip = contact_infos.get(pk)
                if ip is None:
                    new_nodes.remove(pk)
                # we only want to track stuff for DZ-reachable nodes
                elif not self.connection.is_reachable(ip):
                    new_nodes.remove(pk)

            to_remove_nodes = set(self.staked_nodes) - set(new_staked)
            for pk in to_remove_nodes:
                print(f"Removing node {pk} from monitored set")
                node = self.staked_nodes.pop(pk)
                # try to clean the counter in nftables
                nft_del_counter(node.ip_address)

            added = 0
            for pk in new_nodes:
                ip = contact_infos[pk]
                # we only want to track counters for DZ-reachable nodes
                if not self.connection.is_reachable(ip):
                    continue
                self.staked_nodes[pk] = StakedNode(
                    stake=new_staked[pk],
                    ip_address=ip,
                    pubkey=pk,
                    packet_count=0,
                )
                print(f"Add counter for {ip}")
                nft_add_counter(ip)
                added += 1
                # do not add too many conuters all at once to avoid blocking event loop
                if added >= 10:
                    break
            print(f"Added {added}, removed {len(to_remove_nodes)} counters")
            await asyncio.sleep(NODE_REFRESH_INTERVAL_SECONDS)

    async def passive_monitoring(self) -> None:
        """
        Check NFT counters for incoming traffic on active connections to check their health
        """
        dead_nodes: defaultdict[str, int] = defaultdict(int)
        while True:
            await asyncio.sleep(PASSIVE_MONITORING_INTERVAL_SECONDS)
            counters = get_nft_counters()
            reachable_stake = 0.0
            unreachable_stake = 0.0
            for pk, node in self.staked_nodes.items():
                cnt = counters.get(node.ip_address, 0)
                diff = cnt - node.packet_count
                node.packet_count = cnt
                if not self.connection.is_reachable(node.ip_address):
                    continue

                if node.stake == 0:
                    print(node)
                    raise RuntimeError()
                if diff > 0:
                    reachable_stake += node.stake / LAMPORTS_PER_SOL
                else:
                    dead_nodes[pk] += 1
                    unreachable_stake += node.stake / LAMPORTS_PER_SOL
            if unreachable_stake == 0.0 and reachable_stake == 0.0:
                print("No stake from DZ captured in counters...")
                continue
            rec = HealthRecord(
                reachable_stake_fraction=reachable_stake
                / (1 + reachable_stake + unreachable_stake)
            )
            print(
                f"Monitoring: stake reachable {int(reachable_stake)}/{int(reachable_stake + unreachable_stake)} ({rec.reachable_stake_fraction:.1%})"
            )
            self.connection.health_records.append(rec)
            if rec.reachable_stake_fraction < STAKE_THRESHOLD:
                print(f"missing packet counts per node: {dict(dead_nodes)}")
                dead_nodes.clear()

    async def main(self) -> None:
        async with task_group.TaskGroup() as tg:
            tg.create_task(self.refresh_staked_nodes())
            tg.create_task(self.passive_monitoring())
            tg.create_task(self.decision())

    async def decision(self) -> None:
        """
        Goes over the connections ensuring we are using the "best" one.
        """
        # sleep before truly starting this task so we have data to work with
        await asyncio.sleep(WARMUP_PERIOD)
        while True:
            await asyncio.sleep(PASSIVE_MONITORING_INTERVAL_SECONDS)

            # check for obvious issues
            if not await self.connection.self_check():
                print("DZ already disabled")
                continue

            # check if we can still reach target % of stake
            if self.connection.get_best_in_period(GRACE_PERIOD_SEC) < STAKE_THRESHOLD:
                print("Failure condition detected: Disconnecting DZ")
                kill_dz_interface()
                print(self.connection.health_records)
                exit(1)


if __name__ == "__main__":
    with Monitor() as mon:
        asyncio.run(mon.main())
