// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {CUSDC} from "../src/CUSDC.sol";
import {CNGN} from "../src/CNGN.sol";
import {CowrieBridge} from "../src/CowrieBridge.sol";
import {CowrieTreasury} from "../src/CowrieTreasury.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";

/// @dev Each test names the requirement it holds the contract to, so a failure
///      says which part of the SRS broke rather than which line did.
contract CowrieTest is Test {
    CUSDC internal cusdc;
    CNGN internal cngn;
    CowrieBridge internal bridge;

    address internal admin = address(0xA11CE);
    address internal settler = address(0x5E77);
    address internal outsider = address(0xBAD);

    uint256 internal constant ONE = 1e6; // 6 decimals

    function setUp() public {
        vm.startPrank(admin);
        cusdc = new CUSDC(admin);
        cngn = new CNGN(admin);
        bridge = new CowrieBridge(admin, address(cngn), address(cusdc));

        // Fund the bridge with cUSDC liquidity, minted against a real attestation.
        bytes32 ref = keccak256("WIRE-IN-SETUP");
        cusdc.attestReserve(ref, 1_000_000 * ONE);
        cusdc.mintWithAttestation(admin, 1_000_000 * ONE, ref);
        cusdc.approve(address(bridge), type(uint256).max);
        bridge.addLiquidity(500_000 * ONE);

        bridge.grantRole(bridge.SETTLER_ROLE(), settler);
        cngn.mint(settler, 100_000_000 * ONE);
        vm.stopPrank();

        vm.prank(settler);
        cngn.approve(address(bridge), type(uint256).max);
    }

    // ---------------------------------------------------------------------
    // FR 3.2 - cUSDC mint and burn
    // ---------------------------------------------------------------------

    /// FR 3.2: "Reject any attempt to create cUSDC without verified dollar backing."
    function test_FR32_mintWithoutAttestationReverts() public {
        bytes32 unknown = keccak256("NEVER-ATTESTED");

        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(CUSDC.AttestationNotFound.selector, unknown));
        cusdc.mintWithAttestation(admin, 1_000 * ONE, unknown);
    }

    /// FR 3.2: one confirmed deposit must not fund two mints.
    function test_FR32_attestationCannotBeSpentTwice() public {
        bytes32 ref = keccak256("WIRE-IN-DOUBLE");

        vm.startPrank(admin);
        cusdc.attestReserve(ref, 5_000 * ONE);
        cusdc.mintWithAttestation(admin, 5_000 * ONE, ref);

        vm.expectRevert(abi.encodeWithSelector(CUSDC.AttestationAlreadySpent.selector, ref));
        cusdc.mintWithAttestation(admin, 5_000 * ONE, ref);
        vm.stopPrank();
    }

    /// FR 3.2: minting more than the bank confirmed must fail.
    function test_FR32_mintAmountMustMatchAttestation() public {
        bytes32 ref = keccak256("WIRE-IN-MISMATCH");

        vm.startPrank(admin);
        cusdc.attestReserve(ref, 1_000 * ONE);

        vm.expectRevert(
            abi.encodeWithSelector(
                CUSDC.AttestationAmountMismatch.selector, 1_000 * ONE, 9_000 * ONE
            )
        );
        cusdc.mintWithAttestation(admin, 9_000 * ONE, ref);
        vm.stopPrank();
    }

    /// FR 3.2: a happy-path mint increases supply and marks the deposit spent.
    function test_FR32_mintAgainstAttestation() public {
        bytes32 ref = keccak256("WIRE-IN-OK");
        uint256 before = cusdc.totalSupply();

        vm.startPrank(admin);
        cusdc.attestReserve(ref, 2_500 * ONE);
        cusdc.mintWithAttestation(outsider, 2_500 * ONE, ref);
        vm.stopPrank();

        assertEq(cusdc.totalSupply(), before + 2_500 * ONE, "supply should rise by the minted amount");
        assertEq(cusdc.balanceOf(outsider), 2_500 * ONE);

        (, , bool spent) = cusdc.attestationOf(ref);
        assertTrue(spent, "attestation should be marked spent");
    }

    /// FR 3.2: "Destroy cUSDC when redeemed for USD."
    function test_FR32_redeemBurnsSupply() public {
        bytes32 ref = keccak256("WIRE-IN-REDEEM");

        vm.startPrank(admin);
        cusdc.attestReserve(ref, 3_000 * ONE);
        cusdc.mintWithAttestation(admin, 3_000 * ONE, ref);
        uint256 before = cusdc.totalSupply();

        cusdc.redeem(1_000 * ONE, keccak256("WIRE-OUT-1"));
        vm.stopPrank();

        assertEq(cusdc.totalSupply(), before - 1_000 * ONE, "redeem must burn");
    }

    /// Only the reserve oracle may attest.
    function test_FR32_onlyOracleCanAttest() public {
        // Read the role before pranking: vm.prank applies to the next call, and
        // an external getter would consume it.
        bytes32 role = cusdc.RESERVE_ORACLE_ROLE();

        vm.prank(outsider);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, role
            )
        );
        cusdc.attestReserve(keccak256("X"), ONE);
    }

    /// The same wire reference must not be registered twice.
    function test_FR32_attestationCannotBeRegisteredTwice() public {
        bytes32 ref = keccak256("WIRE-IN-DUP");

        vm.startPrank(admin);
        cusdc.attestReserve(ref, ONE);
        vm.expectRevert(abi.encodeWithSelector(CUSDC.AttestationAlreadyRegistered.selector, ref));
        cusdc.attestReserve(ref, ONE);
        vm.stopPrank();
    }

    // ---------------------------------------------------------------------
    // FR 3.1 - atomic bridge call
    // ---------------------------------------------------------------------

    /// FR 3.1: "a single on-chain transaction ... and emits a confirmation event."
    function test_FR31_bridgeIsAtomicAndEmits() public {
        bytes32 ref = keccak256("transfer-1");
        uint256 localAmount = 100_000 * ONE;
        uint256 bridgeAmount = 65 * ONE;

        uint256 settlerCusdcBefore = cusdc.balanceOf(settler);
        uint256 settlerCngnBefore = cngn.balanceOf(settler);

        vm.expectEmit(true, true, false, true);
        emit CowrieBridge.BridgeSettled(ref, localAmount, bridgeAmount, settler, block.timestamp);

        vm.prank(settler);
        bridge.executeBridge(ref, localAmount, bridgeAmount);

        assertEq(cngn.balanceOf(settler), settlerCngnBefore - localAmount, "cNGN must leave");
        assertEq(cusdc.balanceOf(settler), settlerCusdcBefore + bridgeAmount, "cUSDC must arrive");
        assertTrue(bridge.settled(ref), "transfer should be marked settled");
    }

    /// FR 3.1: a retry of the same transfer must not settle twice.
    function test_FR31_bridgeIsIdempotent() public {
        bytes32 ref = keccak256("transfer-2");

        vm.startPrank(settler);
        bridge.executeBridge(ref, 50_000 * ONE, 32 * ONE);

        vm.expectRevert(abi.encodeWithSelector(CowrieBridge.AlreadySettled.selector, ref));
        bridge.executeBridge(ref, 50_000 * ONE, 32 * ONE);
        vm.stopPrank();
    }

    /// FR 3.1: atomicity - if the cUSDC leg cannot be paid, nothing moves.
    function test_FR31_insufficientLiquidityRevertsWholeCall() public {
        bytes32 ref = keccak256("transfer-3");
        uint256 tooMuch = 10_000_000 * ONE;

        uint256 cngnBefore = cngn.balanceOf(settler);
        uint256 liquidity = bridge.availableLiquidity();

        vm.prank(settler);
        vm.expectRevert(
            abi.encodeWithSelector(
                CowrieBridge.InsufficientBridgeLiquidity.selector, liquidity, tooMuch
            )
        );
        bridge.executeBridge(ref, 1_000 * ONE, tooMuch);

        assertEq(cngn.balanceOf(settler), cngnBefore, "no cNGN may move when the call reverts");
        assertFalse(bridge.settled(ref), "a reverted transfer must not be marked settled");
    }

    /// Only the settler role may bridge; an arbitrary caller cannot choose amounts.
    function test_FR31_onlySettlerCanBridge() public {
        bytes32 role = bridge.SETTLER_ROLE();

        vm.prank(outsider);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, role
            )
        );
        bridge.executeBridge(keccak256("x"), ONE, ONE);
    }

    /// A paused bridge stops settling.
    function test_bridgePauseStopsSettlement() public {
        vm.prank(admin);
        bridge.pause();

        vm.prank(settler);
        vm.expectRevert();
        bridge.executeBridge(keccak256("transfer-paused"), ONE, ONE);
    }

    // ---------------------------------------------------------------------
    // NFR 5 - on-chain audit anchoring
    // ---------------------------------------------------------------------

    function test_NFR5_anchorAuditBatchIncrementsSequence() public {
        vm.startPrank(admin);
        bridge.anchorAuditBatch(keccak256("batch-1"));
        bridge.anchorAuditBatch(keccak256("batch-2"));
        vm.stopPrank();

        assertEq(bridge.anchorSequence(), 2, "each batch should advance the anchor sequence");
    }

    function test_NFR5_onlyAnchorRoleCanAnchor() public {
        vm.prank(outsider);
        vm.expectRevert();
        bridge.anchorAuditBatch(keccak256("batch"));
    }

    // ---------------------------------------------------------------------
    // NFR 2 - 3-of-5 treasury multisig
    // ---------------------------------------------------------------------

    function _treasury() internal returns (CowrieTreasury t, address[5] memory s) {
        s = [address(0x51), address(0x52), address(0x53), address(0x54), address(0x55)];
        address[] memory signers = new address[](5);
        for (uint256 i = 0; i < 5; i++) {
            signers[i] = s[i];
        }
        t = new CowrieTreasury(signers);
    }

    /// NFR 2: two signatures are not enough.
    function test_NFR2_twoConfirmationsCannotExecute() public {
        (CowrieTreasury t, address[5] memory s) = _treasury();

        vm.prank(s[0]);
        uint256 txId = t.propose(address(cusdc), 0, abi.encodeCall(cusdc.pause, ()));

        vm.prank(s[1]);
        t.confirm(txId); // now at 2

        vm.prank(s[0]);
        vm.expectRevert(
            abi.encodeWithSelector(CowrieTreasury.NotEnoughConfirmations.selector, 2, 3)
        );
        t.execute(txId);
    }

    /// NFR 2: three of five is the threshold, and it executes.
    function test_NFR2_threeConfirmationsExecute() public {
        (CowrieTreasury t, address[5] memory s) = _treasury();

        // Give the treasury the role it needs to perform the action.
        bytes32 adminRole = cusdc.ADMIN_ROLE();
        vm.prank(admin);
        cusdc.grantRole(adminRole, address(t));

        vm.prank(s[0]);
        uint256 txId = t.propose(address(cusdc), 0, abi.encodeCall(cusdc.pause, ()));
        vm.prank(s[1]);
        t.confirm(txId);
        vm.prank(s[2]);
        t.confirm(txId);

        vm.prank(s[0]);
        t.execute(txId);

        assertTrue(cusdc.paused(), "the treasury action should have taken effect");
    }

    /// NFR 2: a revoked confirmation drops back below the threshold.
    function test_NFR2_revokeDropsBelowThreshold() public {
        (CowrieTreasury t, address[5] memory s) = _treasury();

        vm.prank(s[0]);
        uint256 txId = t.propose(address(cusdc), 0, "");
        vm.prank(s[1]);
        t.confirm(txId);
        vm.prank(s[2]);
        t.confirm(txId); // 3

        vm.prank(s[2]);
        t.revoke(txId); // back to 2

        vm.prank(s[0]);
        vm.expectRevert(
            abi.encodeWithSelector(CowrieTreasury.NotEnoughConfirmations.selector, 2, 3)
        );
        t.execute(txId);
    }

    /// NFR 2: a non-signer cannot participate at all.
    function test_NFR2_nonSignerRejected() public {
        (CowrieTreasury t,) = _treasury();

        vm.prank(outsider);
        vm.expectRevert(abi.encodeWithSelector(CowrieTreasury.NotASigner.selector, outsider));
        t.propose(address(cusdc), 0, "");
    }

    /// NFR 2: the signer set must be exactly five.
    function test_NFR2_signerSetMustBeFive() public {
        address[] memory tooFew = new address[](3);
        tooFew[0] = address(0x1);
        tooFew[1] = address(0x2);
        tooFew[2] = address(0x3);

        vm.expectRevert(abi.encodeWithSelector(CowrieTreasury.InvalidSignerSet.selector, 3));
        new CowrieTreasury(tooFew);
    }

    /// NFR 2: an executed transaction cannot run again.
    function test_NFR2_cannotExecuteTwice() public {
        (CowrieTreasury t, address[5] memory s) = _treasury();

        bytes32 adminRole = cusdc.ADMIN_ROLE();
        vm.prank(admin);
        cusdc.grantRole(adminRole, address(t));

        vm.prank(s[0]);
        uint256 txId = t.propose(address(cusdc), 0, abi.encodeCall(cusdc.pause, ()));
        vm.prank(s[1]);
        t.confirm(txId);
        vm.prank(s[2]);
        t.confirm(txId);

        vm.prank(s[0]);
        t.execute(txId);

        vm.prank(s[0]);
        vm.expectRevert(abi.encodeWithSelector(CowrieTreasury.AlreadyExecuted.selector, txId));
        t.execute(txId);
    }

    // ---------------------------------------------------------------------
    // properties
    // ---------------------------------------------------------------------

    /// Supply can never exceed what the banking partner has confirmed.
    /// This is FR 3.2 stated as an invariant rather than as a code path.
    function testFuzz_FR32_supplyNeverExceedsAttested(uint96 amount) public {
        vm.assume(amount > 0);

        bytes32 ref = keccak256(abi.encode("fuzz", amount));
        vm.startPrank(admin);
        cusdc.attestReserve(ref, amount);
        cusdc.mintWithAttestation(admin, amount, ref);
        vm.stopPrank();

        assertGe(cusdc.totalAttested(), cusdc.totalSupply(), "supply must never exceed attestations");
        assertTrue(cusdc.isFullyAttested());
    }

    /// Bridging any valid amount conserves value: what leaves the bridge equals
    /// what the settler receives.
    function testFuzz_FR31_bridgeConservesValue(uint64 bridgeAmount) public {
        vm.assume(bridgeAmount > 0);
        vm.assume(bridgeAmount <= 400_000 * ONE);

        bytes32 ref = keccak256(abi.encode("fuzz-bridge", bridgeAmount));
        uint256 bridgeBefore = cusdc.balanceOf(address(bridge));
        uint256 settlerBefore = cusdc.balanceOf(settler);

        vm.prank(settler);
        bridge.executeBridge(ref, 1_000 * ONE, bridgeAmount);

        assertEq(cusdc.balanceOf(address(bridge)), bridgeBefore - bridgeAmount);
        assertEq(cusdc.balanceOf(settler), settlerBefore + bridgeAmount);
    }
}
