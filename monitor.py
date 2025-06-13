import subprocess
import json
import ipaddress

NFT_TABLE = "dz_mon"

def get_nft_counters():
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

def nft_add_counter(ip:ipaddress.IPv4Address):
    CMD2 = f"sudo nft add rule inet {NFT_TABLE} input ip saddr {ip} counter"
    (status, output) = subprocess.getstatusoutput(CMD2)

def nft_reset_counters():
    CMD = f"sudo nft reset counters table inet {NFT_TABLE}"
    (status, output) = subprocess.getstatusoutput(CMD)
