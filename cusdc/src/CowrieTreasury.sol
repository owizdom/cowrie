// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @title CowrieTreasury - 3-of-5 multisig over treasury movement
/// @notice Implements NFR 2: "any movement of the treasury requires the
///         signature of a minimum of 3 out of 5 approved signatories."
///
/// @dev In production Cowrie uses a Safe (Gnosis Safe) Smart Account, as SRS
///      §3.3 states. This contract is not a Safe replacement and is not
///      proposed as one - Safe is audited, battle-tested and holds far more
///      value than this ever should. It exists so that the 3-of-5 threshold is
///      a testable property of this repository rather than a claim about a
///      dependency, and so the local Anvil deployment can exercise the treasury
///      path without pulling in Safe's full deployment machinery.
///
///      The design is deliberately minimal: propose, confirm, execute, with
///      confirmations that can be revoked before execution and a transaction
///      that can only execute once.
contract CowrieTreasury {
    uint256 public constant REQUIRED_CONFIRMATIONS = 3;
    uint256 public constant TOTAL_SIGNERS = 5;

    address[] public signers;
    mapping(address => bool) public isSigner;

    struct Transaction {
        address target;
        uint256 value;
        bytes data;
        bool executed;
        uint256 confirmations;
    }

    Transaction[] private _transactions;

    /// @dev txId => signer => confirmed
    mapping(uint256 => mapping(address => bool)) public confirmedBy;

    event Proposed(uint256 indexed txId, address indexed proposer, address target, uint256 value);
    event Confirmed(uint256 indexed txId, address indexed signer, uint256 confirmations);
    event Revoked(uint256 indexed txId, address indexed signer, uint256 confirmations);
    event Executed(uint256 indexed txId, address indexed executor);

    error NotASigner(address caller);
    error InvalidSignerSet(uint256 provided);
    error DuplicateSigner(address signer);
    error ZeroAddress();
    error NoSuchTransaction(uint256 txId);
    error AlreadyExecuted(uint256 txId);
    error AlreadyConfirmed(uint256 txId, address signer);
    error NotConfirmed(uint256 txId, address signer);
    error NotEnoughConfirmations(uint256 have, uint256 need);
    error ExecutionFailed(uint256 txId);

    modifier onlySigner() {
        if (!isSigner[msg.sender]) revert NotASigner(msg.sender);
        _;
    }

    modifier txExists(uint256 txId) {
        if (txId >= _transactions.length) revert NoSuchTransaction(txId);
        _;
    }

    constructor(address[] memory signers_) {
        if (signers_.length != TOTAL_SIGNERS) revert InvalidSignerSet(signers_.length);

        for (uint256 i = 0; i < signers_.length; i++) {
            address signer = signers_[i];
            if (signer == address(0)) revert ZeroAddress();
            if (isSigner[signer]) revert DuplicateSigner(signer);

            isSigner[signer] = true;
            signers.push(signer);
        }
    }

    /// @notice Propose a treasury movement. Counts as the proposer's own
    ///         confirmation, since proposing is an endorsement.
    function propose(address target, uint256 value, bytes calldata data)
        external
        onlySigner
        returns (uint256 txId)
    {
        if (target == address(0)) revert ZeroAddress();

        txId = _transactions.length;
        _transactions.push(
            Transaction({
                target: target,
                value: value,
                data: data,
                executed: false,
                confirmations: 1
            })
        );
        confirmedBy[txId][msg.sender] = true;

        emit Proposed(txId, msg.sender, target, value);
        emit Confirmed(txId, msg.sender, 1);
    }

    function confirm(uint256 txId) external onlySigner txExists(txId) {
        Transaction storage txn = _transactions[txId];
        if (txn.executed) revert AlreadyExecuted(txId);
        if (confirmedBy[txId][msg.sender]) revert AlreadyConfirmed(txId, msg.sender);

        confirmedBy[txId][msg.sender] = true;
        txn.confirmations += 1;

        emit Confirmed(txId, msg.sender, txn.confirmations);
    }

    /// @notice Withdraw a confirmation before execution.
    /// @dev A signer who learns something after confirming must be able to take
    ///      it back; without this, the only way to stop a pending movement
    ///      would be to convince the others not to reach three.
    function revoke(uint256 txId) external onlySigner txExists(txId) {
        Transaction storage txn = _transactions[txId];
        if (txn.executed) revert AlreadyExecuted(txId);
        if (!confirmedBy[txId][msg.sender]) revert NotConfirmed(txId, msg.sender);

        confirmedBy[txId][msg.sender] = false;
        txn.confirmations -= 1;

        emit Revoked(txId, msg.sender, txn.confirmations);
    }

    /// @notice Execute once at least 3 of 5 have confirmed.
    function execute(uint256 txId) external onlySigner txExists(txId) {
        Transaction storage txn = _transactions[txId];
        if (txn.executed) revert AlreadyExecuted(txId);
        if (txn.confirmations < REQUIRED_CONFIRMATIONS) {
            revert NotEnoughConfirmations(txn.confirmations, REQUIRED_CONFIRMATIONS);
        }

        // Set before the call, so a reentrant path finds it already executed.
        txn.executed = true;

        (bool ok,) = txn.target.call{value: txn.value}(txn.data);
        if (!ok) revert ExecutionFailed(txId);

        emit Executed(txId, msg.sender);
    }

    function transactionCount() external view returns (uint256) {
        return _transactions.length;
    }

    function transactionAt(uint256 txId)
        external
        view
        txExists(txId)
        returns (address target, uint256 value, bytes memory data, bool executed, uint256 confirmations)
    {
        Transaction memory txn = _transactions[txId];
        return (txn.target, txn.value, txn.data, txn.executed, txn.confirmations);
    }

    function signerCount() external view returns (uint256) {
        return signers.length;
    }

    receive() external payable {}
}
