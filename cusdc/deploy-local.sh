#!/usr/bin/env bash
#
# Deploy the Cowrie contracts to a local Anvil node and write the address +
# ABI manifest the orchestration tier reads (cusdc/deployments/local.json).
#
# LOCAL ONLY. This talks to 127.0.0.1:8545 and nothing else. There is no code
# path here that reaches Base mainnet or Base Sepolia.
#
# Usage:  ./deploy-local.sh        (assumes anvil is already running)
#         make chain               (starts anvil, then runs this)

set -euo pipefail

CUSDC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RPC_URL="${RPC_URL:-http://127.0.0.1:8545}"

if ! cast block-number --rpc-url "$RPC_URL" > /dev/null 2>&1; then
  echo "No local chain at $RPC_URL."
  echo "Start one with:  anvil --block-time 2"
  exit 1
fi

echo "Deploying to $RPC_URL ..."
cd "$CUSDC_DIR"
forge script script/Deploy.s.sol:Deploy --rpc-url "$RPC_URL" --broadcast -vv > /tmp/cowrie-deploy.log 2>&1 || {
  tail -30 /tmp/cowrie-deploy.log
  exit 1
}

mkdir -p deployments

python3 - "$CUSDC_DIR" <<'PYEOF'
import json, pathlib, re, sys

root = pathlib.Path(sys.argv[1])
log = pathlib.Path("/tmp/cowrie-deploy.log").read_text()

names = ["CUSDC", "CNGN", "CowrieBridge", "CowrieTreasury"]
addresses = {}
for name in names:
    # console.log lines look like:  CUSDC   0x5FbDB...
    match = re.search(rf"^\s*{name}\s+(0x[a-fA-F0-9]{{40}})\s*$", log, re.MULTILINE)
    if match:
        addresses[name] = match.group(1)

missing = [n for n in names if n not in addresses]
if missing:
    print(f"could not find addresses for: {missing}", file=sys.stderr)
    print(log[-2000:], file=sys.stderr)
    sys.exit(1)

abis = {}
for name in names:
    artifact = root / "out" / f"{name}.sol" / f"{name}.json"
    abis[name] = json.loads(artifact.read_text())["abi"]

out = root / "deployments" / "local.json"
out.write_text(json.dumps({
    "network": "anvil-local",
    "chainId": 31337,
    "note": "Local development chain only. Not Base mainnet, not Base Sepolia.",
    "addresses": addresses,
    "abis": abis,
}, indent=2))

print("wrote", out)
for name, addr in addresses.items():
    print(f"  {name:<16} {addr}")
PYEOF

echo
echo "Point the orchestration tier at it with:"
echo "  COWRIE_CHAIN_MODE=anvil uv run uvicorn cowrie.main:app --reload"
