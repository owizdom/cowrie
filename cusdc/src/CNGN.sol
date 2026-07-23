// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title cNGN - local reference implementation of the Nigerian naira stablecoin
/// @notice cNGN is NOT a Cowrie asset. It is issued by the Africa Stablecoin
///         Consortium under the Nigeria SEC sandbox, and Cowrie consumes it as
///         the source spoke of the NGN corridor (SRS §3.3).
///
/// @dev This contract exists so the bridge can be tested end to end on a local
///      chain without the real cNGN deployment. It implements only the surface
///      Cowrie actually uses - transfer, approve, permit - plus an open mint so
///      test fixtures can fund an account.
///
///      The open mint is why this must never be deployed anywhere but a local
///      development chain. On Base, `CowrieBridge` is pointed at the real cNGN
///      address instead, and this file is not deployed at all.
contract CNGN is ERC20, ERC20Permit, Ownable {
    event TestMint(address indexed to, uint256 amount);

    constructor(address owner_)
        ERC20("Compliant Naira", "cNGN")
        ERC20Permit("Compliant Naira")
        Ownable(owner_)
    {}

    /// @notice cNGN uses 6 decimals, as the real issuance does.
    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice Fund an account for local testing.
    /// @dev Owner-only rather than fully open, so a stray local deployment is
    ///      still not a free money faucet for anyone who finds it.
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
        emit TestMint(to, amount);
    }
}
