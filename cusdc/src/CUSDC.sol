// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Burnable} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

/// @title cUSDC - Cowrie's regulated USD-pegged stablecoin
/// @notice The neutral bridge asset for Cowrie's cross-border corridors.
///         Deployed as an ERC-20 on Base, backed 1:1 by USD reserves held with
///         a regulated banking partner.
///
/// @dev Implements FR 3.2: "Only create new cUSDC after the banking partner
///      confirms a matching USD deposit. Destroy cUSDC when redeemed for USD.
///      Reject any attempt to create cUSDC without verified dollar backing."
///
///      The third sentence is the one that shapes this contract. There is no
///      plain `mint(address,uint256)`. The only way to create supply is
///      `mintWithAttestation`, which requires an attestation reference that the
///      reserve oracle has already registered, and each reference can be spent
///      exactly once. That makes double-minting against a single USD deposit
///      impossible at the contract level rather than merely discouraged by
///      process.
///
///      Uses 6 decimals to match USDC on Base, so integrations that already
///      handle USDC amounts do not need a second scaling path.
contract CUSDC is ERC20, ERC20Burnable, ERC20Permit, AccessControl, Pausable {
    /// @notice Held by the Safe multisig; may pause and grant roles.
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");

    /// @notice Held by the reserve service; registers confirmed USD deposits.
    bytes32 public constant RESERVE_ORACLE_ROLE = keccak256("RESERVE_ORACLE_ROLE");

    /// @notice Held by the issuance service; mints against registered deposits.
    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE");

    /// @notice A USD deposit the banking partner has confirmed.
    struct Attestation {
        uint256 amount;
        uint64 confirmedAt;
        bool spent;
    }

    /// @dev Deposit reference => attestation. The reference is the banking
    ///      partner's own wire reference, hashed.
    mapping(bytes32 => Attestation) private _attestations;

    /// @notice Total USD confirmed by the banking partner over all time.
    uint256 public totalAttested;

    event ReserveAttested(bytes32 indexed depositRef, uint256 amount, uint64 confirmedAt);
    event MintedAgainstReserve(bytes32 indexed depositRef, address indexed to, uint256 amount);
    event RedeemedForUsd(address indexed from, uint256 amount, bytes32 indexed wireRef);

    error AttestationNotFound(bytes32 depositRef);
    error AttestationAlreadySpent(bytes32 depositRef);
    error AttestationAmountMismatch(uint256 attested, uint256 requested);
    error AttestationAlreadyRegistered(bytes32 depositRef);
    error ZeroAmount();

    constructor(address admin)
        ERC20("Cowrie USD Coin", "cUSDC")
        ERC20Permit("Cowrie USD Coin")
    {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        // The deployer holds the operational roles at genesis; in production the
        // Safe reassigns them to the reserve and issuance services.
        _grantRole(RESERVE_ORACLE_ROLE, admin);
        _grantRole(ISSUER_ROLE, admin);
    }

    /// @notice cUSDC uses 6 decimals, matching USDC on Base.
    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice Record a USD deposit confirmed by the banking partner.
    /// @dev The gate in front of all issuance. Only the reserve oracle can call
    ///      this, and a reference cannot be registered twice.
    function attestReserve(bytes32 depositRef, uint256 amount)
        external
        onlyRole(RESERVE_ORACLE_ROLE)
    {
        if (amount == 0) revert ZeroAmount();
        if (_attestations[depositRef].confirmedAt != 0) {
            revert AttestationAlreadyRegistered(depositRef);
        }

        _attestations[depositRef] =
            Attestation({amount: amount, confirmedAt: uint64(block.timestamp), spent: false});
        totalAttested += amount;

        emit ReserveAttested(depositRef, amount, uint64(block.timestamp));
    }

    /// @notice Mint cUSDC against a registered, unspent USD deposit.
    /// @dev FR 3.2. Reverts if the reference was never attested, was already
    ///      used, or does not match the requested amount exactly. Exact-match
    ///      rather than "at most" is deliberate: partial draws against one
    ///      deposit would make the one-reference-one-mint invariant much harder
    ///      to reason about, and the reserve service has no need for them.
    function mintWithAttestation(address to, uint256 amount, bytes32 depositRef)
        external
        onlyRole(ISSUER_ROLE)
        whenNotPaused
    {
        Attestation storage attestation = _attestations[depositRef];

        if (attestation.confirmedAt == 0) revert AttestationNotFound(depositRef);
        if (attestation.spent) revert AttestationAlreadySpent(depositRef);
        if (attestation.amount != amount) {
            revert AttestationAmountMismatch(attestation.amount, amount);
        }

        attestation.spent = true;
        _mint(to, amount);

        emit MintedAgainstReserve(depositRef, to, amount);
    }

    /// @notice Burn cUSDC on redemption for USD.
    /// @dev Distinct from the inherited `burn` so redemptions carry the wire
    ///      depositRef the dollars went out on, which is what makes the burn
    ///      reconcilable against the bank statement.
    function redeem(uint256 amount, bytes32 wireRef) external whenNotPaused {
        if (amount == 0) revert ZeroAmount();
        _burn(msg.sender, amount);
        emit RedeemedForUsd(msg.sender, amount, wireRef);
    }

    /// @notice Look up an attestation by its deposit reference.
    function attestationOf(bytes32 depositRef)
        external
        view
        returns (uint256 amount, uint64 confirmedAt, bool spent)
    {
        Attestation memory a = _attestations[depositRef];
        return (a.amount, a.confirmedAt, a.spent);
    }

    /// @notice True when circulating supply is fully covered by attested USD.
    /// @dev A view over what the contract itself knows. The authoritative
    ///      coverage check also compares against the bank's live balance, which
    ///      is off-chain; this is the on-chain half.
    function isFullyAttested() external view returns (bool) {
        return totalAttested >= totalSupply();
    }

    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /// @dev Transfers stop while paused. Pausing a settlement asset is a serious
    ///      step, which is why it sits behind the Safe rather than an operator.
    function _update(address from, address to, uint256 value)
        internal
        override
        whenNotPaused
    {
        super._update(from, to, value);
    }
}
