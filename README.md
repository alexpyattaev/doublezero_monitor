# doublezero_monitor

Super basic daemon to monitor quality of different connections.
sudo access to `nft` command should be granted to use this.
Edit the script to configure the parameters.

```bash
./monitor.py
```
# ToDos

* Tune all the timings
* Cascade the pings in active monitoring better to avoid bursts of traffic
* Test on an actually multihomed box
* Switch to named counters in nftables?
* rewrite it in Rust (tm)
