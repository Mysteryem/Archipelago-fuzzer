# Hook that mirrors the core AP test test.test_implemented.TestBase.test_prefill_items.
# When fuzzing with this as the only hook, generation finishes after the test is run.
# Known core-verified failures...:
# - marioland2
# - messenger
# - ffmq
# - kh2
# - sm
# - zillion
# - pokemon_emerald
# - sc2
# - terraria
# - oot
# - alttp
# - timespinner
# Known custom failures:
# - tje
# - tevi
# - diddy_kong_racing
# - hcniko
# - tloz_ooa
# - another_crab
# - zelda2
# - metroidprime
# - swr
# - voidstranger
# - pokemon_bw
# - Twilight Princess
# - checksmate
# - none_sols
# - ffxiv
# - ittle_dew_2
# - animal_well
from typing import Any

from worlds import AutoWorld
from BaseClasses import MultiWorld

from fuzz import BaseHook, GenOutcome


class HookTestSuccess(Exception):
    pass


class HookTestFailure(Exception):
    pass


# Mirroring test.test_implemented.TestBase.test_prefill_items.
def _test_prefill_items(multiworld: MultiWorld):
    """Test that every world can reach every location from allstate before pre_fill."""
    all_state = multiworld.get_all_state()
    unreachable_locations = [loc for loc in multiworld.get_locations() if not loc.can_reach(all_state)]
    if unreachable_locations:
        raise HookTestFailure(
            f"Locations were not reachable with an all-state before pre_fill: {unreachable_locations}")


class Hook(BaseHook):
    def setup_worker(self, args):
        super().setup_worker(args)
        # Monkey patch AutoWorld.call_all to run the test right before the `pre_fill` step.
        original = AutoWorld.call_all

        early_success_return = len(args.hook) == 1

        def replacement_call_all(multiworld: MultiWorld, method_name: str, *args: Any) -> None:
            if method_name == "pre_fill":
                _test_prefill_items(multiworld)
                if early_success_return:
                    # Allow the generation to return early by raising an Exception that is later reclassified to
                    # success.
                    raise HookTestSuccess()
            original(multiworld, method_name, *args)

        AutoWorld.call_all = replacement_call_all

    def reclassify_outcome(self, outcome, raised):
        if isinstance(raised, HookTestSuccess):
            # Reclassify an early success return.
            return GenOutcome.Success, None
        else:
            return super().reclassify_outcome(outcome, raised)
