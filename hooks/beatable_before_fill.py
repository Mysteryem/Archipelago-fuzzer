# Test that the multiworld is beatable with all items from the item pool, before Core AP's main fill (directly after
# stage_fill_hook).
# If any world in the multiworld is not beatable, then there is a very high chance that generation will fail.
# Some worlds may try to adjust rules after Core AP's main fill, e.g. in post_fill, to make the multiworld beatable, but
# doing so will prevent `accessibility: minimal` from having any effect on item placements, which is considered a bug.
from typing import Any

from BaseClasses import MultiWorld, CollectionState, Item
from Options import OptionError

from fuzz import BaseHook, GenOutcome, MP_HOOKS

class HookTestFailure(Exception):
    pass

class HookTestEarlySuccess(Exception):
    pass

class Hook(BaseHook):
    _patched_function_called = False

    def setup_worker(self, args):
        super().setup_worker(args)
        self._patched_function_called = False

        # Monkey patch the `AutoWorld.call_all` call in `Fill.distribute_items_restrictive` to check that the multiworld
        # is beatable with an all-state before AP's main progression fill(s).
        # Fill.py imports `from worlds.AutoWorld import call_all`, so replacing `AutoWorld.call_all` won't work to
        # perform the monkey-patch, instead `Fill.call_all` must be replaced.
        import Fill
        original = Fill.call_all

        # If this is the only hook, then it can return early once the hook's tests have passed.
        early_success_return = len(MP_HOOKS) == 1

        def replacement_call_all(multiworld: "MultiWorld", method_name: str, *args: Any) -> None:
            self._patched_function_called = True
            # Run the normal per-world and per-game generation step.
            original(multiworld, method_name, *args)
            # fill_hook is the last step before core AP's main progression fills: priority fill(s) + progression fill.
            if method_name == "fill_hook":
                # Now check that all worlds can goal with all items that have yet to be placed.
                prog_item_pool: list[Item] = args[0]
                state = CollectionState(multiworld)
                for item in prog_item_pool:
                    if item.advancement:
                        state.collect(item, prevent_sweep=True)
                if not multiworld.can_beat_game(state):
                    raise HookTestFailure(
                        "The Multiworld is unbeatable with all items from the item pool collected immediately before "
                        "AP's core fill (directly after stage_fill_hook). This usually indicates that this multiworld "
                        "would have been impossible to generate a beatable seed with which is almost always a bug in "
                        "one of the worlds in this multiworld. This also prevents `accessibility: minimal` from "
                        "working properly, so this is a bug even if a world is 'fixing' its logic in post_fill, or "
                        "later.")
                if early_success_return:
                    # Allow the generation to return early by raising an Exception that is later reclassified to
                    # success.
                    raise HookTestEarlySuccess()

        Fill.call_all = replacement_call_all

    def after_generate(self, mw, output_path):
        super().after_generate(mw, output_path)
        if mw is not None and not self._patched_function_called:
            raise Exception("Fuzzer Hook Error: The multiworld generated, but the patched function was not called.")

    def reclassify_outcome(self, outcome, raised):
        if isinstance(raised, HookTestEarlySuccess):
            # Reclassify an early success return.
            return GenOutcome.Success, None
        if raised is not None and not isinstance(raised, (OptionError, HookTestFailure)):
            # Ignore other generation errors that are not what the hook is testing for.
            return GenOutcome.OptionError, None
        return super().reclassify_outcome(outcome, raised)
