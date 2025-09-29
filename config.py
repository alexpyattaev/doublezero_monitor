
# Tunable parameters

# Which cluster to connect to (fed to solana CLI)
CLUSTER="testnet" # "mainnet-beta"

# how much stake do we need to observe to consider connection "good"
STAKE_THRESHOLD: float = 0.9
# How long do we accumulate packets before checking the counters
PASSIVE_MONITORING_INTERVAL_SECONDS: float = 5.0
# How long do we wait before consindering connection dead
GRACE_PERIOD_SEC: float = 10.0
# Interval between refreshes of gossip tables via RPC
NODE_REFRESH_INTERVAL_SECONDS: float = 60.0

# Path to the admin RPC socket of the validator
ADMIN_RPC_PATH="/home/sol/ledger/admin.rpc"

# Parameters you should probably not tune

# Table to create in nftables
NFT_TABLE = "dz_mon"

LAMPORTS_PER_SOL = 1000000000
# Minimal stake of node for us to care about it
# Setting this higher reduces overheads of monitoring
MIN_STAKE_TO_CARE = LAMPORTS_PER_SOL * 50000
