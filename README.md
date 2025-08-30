# doublezero monitor

Super basic daemon to monitor quality of different connections.
sudo access to `nft` command should be granted to use this, alternatively run 
this script under root.
Edit the script to configure the parameters.

A systemd unit `doublezero_monitor.service` is also provided, edit as appropriate.


## For IBRL mode use 
```bash
./monitor_ibrl.py
```

## For edge filtration mode use 
```bash
./monitor.py
```
You will have to configure the validator for multihoming, and sync up the list of IP addresses in validator config and in the script


# ToDos

* Tune all the timings for mainnet
* Cascade the pings in active monitoring better to avoid bursts of traffic
* Test on an actually multihomed box
* Switch to named counters in nftables?
* rewrite it in Rust (tm)
