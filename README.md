# doublezero monitor

Simple daemon to monitor quality of DZ connection and detect subtle failure modes that
DZ daemon can not detect on its own.

*These scripts may modify nftables state and may interact with the validator*.
Please understand what the entire script does before running it to make sure it will not break
anything on your system.

This works by counting packets coming to the validator, and if there are no packets
from a sufficintly high % of stake, it will disconnect DZ "just in case".

This will not trigger on minor DZ packet loss, only substantial failures in the network configuration.


## Installation

Edit the `config.py` file to configure the parameters to your liking.

It is recommended that you run this script from the sol user account (assuming it also has
access to the `doublezero` command line). Sudo access to the `nft` command
should be granted to use this as an unpriviledged user. Running this in tmux/zellij
is a viable way to test that the parameters are chosen correctly.

For permanent install it is recommended to have a systemd service configured to
ensure the monitor starts every time the hosts reboots.
A systemd unit `doublezero_monitor.service` is provided, install as appropriate for your system.
```bash
sudo cp doublezero_monitor.service /etc/systemd/system/
```

Keep in mind that when running as system service, the script will still need access to both `solana`
and `doublezero` binaries to perform its function. To check, log in as a root user and verify
that both commands can still be executed.

In addition, you should make the DZ config available to the root user as follows:
```bash
mkdir -p /root/.config/doublezero/
ln -s /home/sol/.config/doublezero/cli  /root/.config/doublezero/cli
```

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

# Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
