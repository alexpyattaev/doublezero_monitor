import subprocess
import json
import ipaddress
import asyncio
import dataclasses

NFT_TABLE = "dz_mon"

def get_nft_counters()->dict[ipaddress.IPv4Address, int]:
    CMD=f"sudo nft -j list chain inet {NFT_TABLE} input"
    (status, output) = subprocess.getstatusoutput(CMD)
    x = json.loads(output)
    rules = x['nftables'][2]
    counters = {}
    for r in rules:
        expr = r['expr']
        source = ipaddress.ip_address(expr[0]['match']['right'])
        counter =expr[1]['counter']['packets']
        counters[source] = counter
    return counters

def nft_add_counter(ip:ipaddress.IPv4Address):
    CMD2 = f"sudo nft add rule inet {NFT_TABLE} input ip saddr {ip} counter"
    (status, output) = subprocess.getstatusoutput(CMD2)

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
    CMD = "-um validators --output json"
    proc = await asyncio.create_subprocess_exec("solana", *CMD.split(" "), stdout=asyncio.subprocess.PIPE,
           stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    output = json.loads(stdout)
    return [v['identityPubkey'] for v in output["validators"]  if v['activatedStake'] > 0 and not v['delinquent']]

async def get_contact_infos():
    CMD = "-um gossip --output json"
    proc = await asyncio.create_subprocess_exec("solana", *CMD.split(" "), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    output = json.loads(stdout)
    return  {v['identityPubkey']:v['ipAddress'] for v in output if 'tpuPort' in v}

@dataclasses.dataclass
class StakedNode:
    pubkey:str
    ip_address: ipaddress.IPv4Address
    stake: int
    on_doublezero: bool

class Monitor:
    staked_nodes = {}
    contact_infos = {}

    def __init__(self) -> None:
        pass


    async def refresh_staked_nodes(self):
        while True:
            print("Refreshing staked nodes")
            self.contact_infos = await get_contact_infos()
            new_staked = await get_staked_nodes()

            new_nodes = set(new_staked) - set(self.staked_nodes)
            for pk, n in new_nodes.items():
                ip = self.contact_infos[pk]
                print(f"Add counter for {ip}")
                self.staked_nodes[pk] = StakedNode(stake = new_staked)
                #await nft_add_counter(ip)
            await asyncio.sleep(300)


    async def check_counters(self)->None:
        while True:
            print("Checking counters")
            counters = get_nft_counters()

            nft_reset_counters()
            await asyncio.sleep(1)

    async def main(self)->None:
        async with asyncio.TaskGroup() as tg:
            task1 = tg.create_task(self.refresh_staked_nodes())
        while True:
            if doublezero_is_active():
                await self.passive_monitoring()
            else:
                await self.active_monitoring()

    # Monitor DZ connection quality by observing ingress traffic
    # This is more efficient but only works when DZ is in use
    async def passive_monitoring(self) -> None:
        print("Using passive monitoring")
        async with asyncio.TaskGroup() as tg:
            task1 = tg.create_task(self.check_counters)



    # Monitor DZ connection quality by actively pinging hosts
    # This is needed when DZ is not active and no traffic can be expected
    async def active_monitoring(self)->None:
        print("Using active monitoring")
        #TODO: implement this
        pass



if __name__=="__main__":
    mon = Monitor()
    asyncio.run(mon.main())
