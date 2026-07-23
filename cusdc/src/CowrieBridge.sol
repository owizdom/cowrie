// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import {CUSDC} from "./CUSDC.sol";

/// @title CowrieBridge - the neutral settlement bridge
/// @notice Converts a local stablecoin (cNGN) into cUSDC in a single atomic
///         transaction, and emits the event the orchestration tier watches.
///
/// @dev Implements FR 3.1: "Execute each transfer as a single on-chain
///      transaction on Base that converts the sender's local stablecoin (cNGN)
///      through cUSDC and emits a confirmation event."
///
///      Atomicity is the requirement. Either the cNGN moves into the bridge's
///      liquidity and the cUSDC leaves it, or neither happens and the whole
///      call reverts. There is no intermediate state in which a sender's cNGN
///      has been taken but no cUSDC exists, which is what would make the
///      settlement guarantee in NFR 3 impossible to honour on-chain.
///
///      What this contract deliberately does not do is hold an exchange rate.
///      Pricing is decided by the quote engine off-chain and passed in, because
///      a rate oracle on an L2 would be both a cost and an attack surface for a
///      corridor whose price is already locked for 60 seconds at quote time.
///      The `SETTLER_ROLE` gate is what makes that safe: only Cowrie's signing
///      service can call `executeBridge`, so the amounts cannot be chosen by an
///      arbitrary caller.
contract CowrieBridge is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");

    /// @notice Held by Cowrie's signing service; the only caller that can settle.
    bytes32 public constant SETTLER_ROLE = keccak256("SETTLER_ROLE");

    /// @notice Held by the audit service; anchors audit-log batch hashes.
    bytes32 public constant ANCHOR_ROLE = keccak256("ANCHOR_ROLE");

    IERC20 public immutable localStablecoin; // cNGN
    CUSDC public immutable bridgeAsset; // cUSDC

    /// @dev transferRef => settled. Prevents the same corridor transfer being
    ///      settled twice if the orchestration tier retries after a timeout it
    ///      logged but the chain actually accepted.
    mapping(bytes32 => bool) public settled;

    uint256 public totalBridged;
    uint256 public settlementCount;

    /// @notice FR 3.1's "confirmation event". The orchestration tier counts
    ///         confirmations on the block containing this.
    event BridgeSettled(
        bytes32 indexed transferRef,
        uint256 localAmount,
        uint256 bridgeAmount,
        address indexed settler,
        uint256 timestamp
    );

    /// @notice NFR 5's on-chain anchor for a batch of audit-log entries.
    event AuditBatchAnchored(bytes32 indexed batchHash, uint256 indexed sequence, uint256 timestamp);

    event LiquidityAdded(address indexed token, uint256 amount);
    event LiquidityWithdrawn(address indexed token, address indexed to, uint256 amount);

    error AlreadySettled(bytes32 transferRef);
    error ZeroAmount();
    error InsufficientBridgeLiquidity(uint256 available, uint256 required);

    uint256 public anchorSequence;

    constructor(address admin, address localStablecoin_, address bridgeAsset_) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(SETTLER_ROLE, admin);
        _grantRole(ANCHOR_ROLE, admin);

        localStablecoin = IERC20(localStablecoin_);
        bridgeAsset = CUSDC(bridgeAsset_);
    }

    /// @notice Settle one corridor transfer: cNGN in, cUSDC out, atomically.
    /// @param transferRef Cowrie's transfer id, hashed. Idempotency key.
    /// @param localAmount cNGN taken from the settler's balance.
    /// @param bridgeAmount cUSDC released from bridge liquidity.
    ///
    /// @dev nonReentrant even though both tokens are known and trusted: the
    ///      bridge is the contract that would hold real liquidity, and a token
    ///      upgrade that introduced a callback should not be able to turn into
    ///      a drain. The cost is a few thousand gas on an L2 where gas is
    ///      fractions of a cent.
    function executeBridge(bytes32 transferRef, uint256 localAmount, uint256 bridgeAmount)
        external
        onlyRole(SETTLER_ROLE)
        whenNotPaused
        nonReentrant
    {
        if (settled[transferRef]) revert AlreadySettled(transferRef);
        if (localAmount == 0 || bridgeAmount == 0) revert ZeroAmount();

        uint256 available = bridgeAsset.balanceOf(address(this));
        if (available < bridgeAmount) {
            revert InsufficientBridgeLiquidity(available, bridgeAmount);
        }

        // Marked before any external call: the reentrancy guard already covers
        // this, but the ordering costs nothing and does not depend on it.
        settled[transferRef] = true;
        totalBridged += bridgeAmount;
        settlementCount += 1;

        // Both legs, or neither. A revert in either unwinds the whole call.
        localStablecoin.safeTransferFrom(msg.sender, address(this), localAmount);
        IERC20(address(bridgeAsset)).safeTransfer(msg.sender, bridgeAmount);

        emit BridgeSettled(transferRef, localAmount, bridgeAmount, msg.sender, block.timestamp);
    }

    /// @notice Anchor the head hash of a batch of audit-log entries (NFR 5).
    /// @dev One transaction per batch rather than per entry. Because each audit
    ///      entry commits to its predecessor, anchoring the head of a batch
    ///      anchors every entry before it.
    function anchorAuditBatch(bytes32 batchHash) external onlyRole(ANCHOR_ROLE) {
        anchorSequence += 1;
        emit AuditBatchAnchored(batchHash, anchorSequence, block.timestamp);
    }

    /// @notice Fund the bridge with cUSDC liquidity.
    function addLiquidity(uint256 amount) external onlyRole(ADMIN_ROLE) {
        IERC20(address(bridgeAsset)).safeTransferFrom(msg.sender, address(this), amount);
        emit LiquidityAdded(address(bridgeAsset), amount);
    }

    /// @notice Withdraw liquidity. Admin is the Safe, so this is a 3-of-5 action.
    function withdrawLiquidity(address token, address to, uint256 amount)
        external
        onlyRole(ADMIN_ROLE)
    {
        IERC20(token).safeTransfer(to, amount);
        emit LiquidityWithdrawn(token, to, amount);
    }

    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /// @notice Available cUSDC liquidity.
    function availableLiquidity() external view returns (uint256) {
        return bridgeAsset.balanceOf(address(this));
    }
}
