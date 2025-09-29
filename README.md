# doublezero monitor

Simple daemon to monitor quality of DZ connection and detect subtle failure modes that
DZ daemon can not detect on its own.

This works by counting packets coming to the validator, and if there are no packets
from a sufficintly high % of stake, it will disconnect DZ "just in case".

This will not trigger on minor DZ packet loss, only substantial failures in the network configuration.

## Installation
sudo access to `nft` command should be granted to use this, alternatively you
could run this script under root. This script will modify nftables state.
Inspect the entire script before running it to make sure it will not break
anything on your system.

Edit the `config.py` file to configure the parameters.

A systemd unit `doublezero_monitor.service` is also provided, install as appropriate for your system.

## For IBRL mode

use
```bash
./monitor_ibrl.py
```
Once the script disconnects DZ, it will not automatically reconnect it, as it has no way to test if
DZ is back or not short of switching the validator to a potentially broken configuration.

## For edge filtration mode

use
```bash
./monitor.py
```
You will have to configure the validator for multihoming, and sync up the list of IP addresses in validator config and in the script.

# ToDos
PRs are welcome!
* Cascade the pings in active monitoring better to avoid bursts of traffic
* Switch to named counters in nftables?
* rewrite it in Rust (tm)
