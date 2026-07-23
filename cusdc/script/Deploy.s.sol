// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Script, console} from "forge-std/Script.sol";
import {CUSDC} from "../src/CUSDC.sol";
import {CNGN} from "../src/CNGN.sol";
import {CowrieBridge} from "../src/CowrieBridge.sol";
import {CowrieTreasury} from "../src/CowrieTreasury.sol";

/// @title Local deployment
/// @notice Deploys the full Cowrie contract set to a local Anvil node and funds
///         it so the orchestration tier can settle real transactions against it.
///
/// @dev LOCAL ONLY. This script is not for Base mainnet or Base Sepolia. It
///      uses Anvil's first published development account, deploys a mock cNGN
///      that the real corridor would never use, and mints itself liquidity.
///      Deploying this anywhere with real value would be a serious mistake, so
///      it takes no RPC URL argument and defaults to 127.0.0.1.
///
///      Run with: make chain   (see the repository Makefile)
contract Deploy is Script {
    /// Anvil's first default account. Published in Foundry's documentation, and
    /// therefore worthless outside a local node.
    uint256 internal constant ANVIL_KEY =
        0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;

    uint256 internal constant ONE = 1e6;

    function run() external {
        uint256 deployerKey = vm.envOr("PRIVATE_KEY", ANVIL_KEY);
        address deployer = vm.addr(deployerKey);

        vm.startBroadcast(deployerKey);

        CUSDC cusdc = new CUSDC(deployer);
        CNGN cngn = new CNGN(deployer);
        CowrieBridge bridge = new CowrieBridge(deployer, address(cngn), address(cusdc));

        address[] memory signers = new address[](5);
        signers[0] = deployer;
        signers[1] = address(0x5151);
        signers[2] = address(0x5252);
        signers[3] = address(0x5353);
        signers[4] = address(0x5454);
        CowrieTreasury treasury = new CowrieTreasury(signers);

        // Seed the bridge with cUSDC liquidity, through the same attested path
        // production uses - there is no shortcut that skips the reserve gate.
        bytes32 genesisDeposit = keccak256("GENESIS-RESERVE-DEPOSIT");
        cusdc.attestReserve(genesisDeposit, 12_400_128 * ONE);
        cusdc.mintWithAttestation(deployer, 12_400_128 * ONE, genesisDeposit);

        cusdc.approve(address(bridge), type(uint256).max);
        bridge.addLiquidity(5_000_000 * ONE);

        // Fund the settler with cNGN, and approve the bridge to pull it.
        // executeBridge does a transferFrom on the local stablecoin, so without
        // this approval every settlement reverts with ERC20InsufficientAllowance.
        cngn.mint(deployer, 10_000_000_000 * ONE);
        cngn.approve(address(bridge), type(uint256).max);

        vm.stopBroadcast();

        console.log("CUSDC          ", address(cusdc));
        console.log("CNGN           ", address(cngn));
        console.log("CowrieBridge   ", address(bridge));
        console.log("CowrieTreasury ", address(treasury));
        console.log("deployer       ", deployer);
    }
}
