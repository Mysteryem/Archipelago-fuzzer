"""
A fuzzer hook that detects missing indirect conditions and reports the tracebacks of the entrance rules that are missing
indirect conditions.

This hook cannot detect issues with worlds that entirely override can_reach() in their Region subclasses to no longer
call the normal CollectionState.update_reachable_regions(), e.g. OoT has its own implementation to handle its two
separate region graphs.

This hook can detect missing indirect conditions that have no effect on logic. This can happen because either:
a. The region whose access is being checked is always accessible before the entrance is checked for being accessible.
b. The entrance is always accessible before the region is accessible, for example, if the entrance rule is
  `state.can_reach_region("my_region", self.player) or state.has("my_event", self.player)` and "my_event" is always
  collected before "my_region" becomes accessible.
"""

import traceback
from collections import deque

from fuzz import BaseHook, GenOutcome

from BaseClasses import CollectionState, Entrance, MultiWorld, Region


class HookMissingIndirectConditionError(Exception):
    pass


class HookUndefinedBehaviourError(Exception):
    pass


class HookIndirectConditionCheckingCollectionState(CollectionState):
    """Rather than patching CollectionState, this CollectionState subclass is used."""
    _hook_last_entrance: Entrance | None = None

    # Copied from github.com/ArchipelagoMW/Archipelago at b372b02273436874dd7c5ce145387f96339eb5ed, and then modified.
    def _update_reachable_regions_explicit_indirect_conditions(self, player: int, queue: deque[Entrance]):
        reachable_regions = self.reachable_regions[player]
        blocked_connections = self.blocked_connections[player]
        # run BFS on all connections, and keep track of those blocked by missing items
        while queue:
            connection = queue.popleft()
            new_region = connection.connected_region
            if new_region in reachable_regions:
                blocked_connections.remove(connection)
            else:
                # New code start.
                if self._hook_last_entrance is not None:
                    # A recursive call does not sound good, it could recurse again, and updating `reachable_regions` and
                    # `blocked_connections` while they are in the middle of being updated does not sound good either.
                    raise HookUndefinedBehaviourError(
                        f"_update_reachable_regions_explicit_indirect_conditions has been called by"
                        f" Entrance.can_reach() on {self._hook_last_entrance}. Recursively calling"
                        f" `_update_reachable_regions_explicit_indirect_conditions()` from itself, which is undefined"
                        f" behaviour.")
                self._hook_last_entrance = connection
                # Region.can_reach() calls made by calling `connection.can_reach(self)` will check for indirect
                # conditions being registered between `connection` and the region in question.
                reachable = connection.can_reach(self)
                self._hook_last_entrance = None
                # `if reachable` replaces `elif connection.can_reach(self)`.
                if reachable:
                    # New code end.
                    if self.allow_partial_entrances and not new_region:
                        continue
                    assert new_region, f"tried to search through an Entrance \"{connection}\" with no connected Region"
                    reachable_regions.add(new_region)
                    blocked_connections.remove(connection)
                    blocked_connections.update(new_region.exits)
                    queue.extend(new_region.exits)
                    self.path[new_region] = (new_region.name, self.path.get(connection, None))
                    self.multiworld.worlds[player].reached_region(self, new_region)

                    # Retry connections if the new region can unblock them
                    entrances = self.multiworld.indirect_connections.get(new_region)
                    if entrances is not None:
                        relevant_entrances = entrances.intersection(blocked_connections)
                        relevant_entrances.difference_update(queue)
                        queue.extend(relevant_entrances)


def iterate_all_spheres(state: CollectionState):
    """Like multiworld.get_spheres(), but for the given CollectionState, and without yielding the spheres."""
    locations = set(state.multiworld.get_locations())
    while locations:
        reachable = [loc for loc in locations if loc.can_reach(state)]
        if not reachable:
            # No more reachable locations.
            break
        for loc in reachable:
            item = loc.item
            if item is not None and item.advancement:
                state.collect(item, True, loc)
        locations.difference_update(reachable)


class Hook(BaseHook):
    failures: list[str]
    seen_region_access_by_an_entrance: set[tuple[Entrance, Region]]

    def setup_main(self, args):
        super().setup_main(args)
        self.failures = []
        self.seen_region_access_by_an_entrance = set()

    def before_generate(self, args):
        super().before_generate(args)
        self.failures = []
        self.seen_region_access_by_an_entrance = set()

    def after_generate(self, mw: MultiWorld | None, output_path) -> None:
        super().after_generate(mw, output_path)
        if mw is None:
            # Generation failed for some reason.
            return

        if not any(world.explicit_indirect_conditions for world in mw.worlds.values()):
            # No worlds in this multiworld use explicit indirect conditions.
            return

        try:
            # Patch Region.can_reach for all regions in the multiworld that belong to a world that uses explicit
            # indirect conditions.
            for world in mw.worlds.values():
                if not world.explicit_indirect_conditions:
                    continue
                for r in world.get_regions():
                    self.patch_region_can_reach(r)
            # Create a test state and iterate spheres so that access to locations/entrances/regions is tested.
            state = HookIndirectConditionCheckingCollectionState(mw)
            iterate_all_spheres(state)
        finally:
            # Clear out `self.seen_region_access_by_an_entrance` to allow the entrances and regions within it to be
            # garbage collected sooner than the next `before_generate()` call.
            self.seen_region_access_by_an_entrance.clear()

    def reclassify_outcome(self, outcome, raised):
        if outcome == GenOutcome.Success:
            if self.failures:
                assert raised is None
                formatted_failures = "\n".join(self.failures)
                failure_message = f"Missing indirect conditions detected:\n{formatted_failures}"
                return GenOutcome.Failure, HookMissingIndirectConditionError(failure_message)
            else:
                return super().reclassify_outcome(outcome, raised)
        else:
            if isinstance(raised, HookUndefinedBehaviourError):
                return super().reclassify_outcome(outcome, raised)
            # Some other error occurred, ignore it.
            return GenOutcome.OptionError, None

    def patch_region_can_reach(self, r: Region):
        original = r.can_reach

        def region_can_reach_fuzzer_hook_override(state: CollectionState) -> bool:
            last_entrance = getattr(state, "_hook_last_entrance", None)
            if last_entrance is not None and last_entrance.parent_region is not r:
                key = (last_entrance, r)
                if key not in self.seen_region_access_by_an_entrance:
                    self.seen_region_access_by_an_entrance.add(key)
                    indirect_conditions = state.multiworld.indirect_connections.get(r)
                    if indirect_conditions is None or last_entrance not in indirect_conditions:
                        if last_entrance.connected_region is r:
                            # Technically, worlds can have an entrance to a region that is only accessible once the
                            # player already has access to that region, e.g. entering the region unlocks a shortcut
                            # back to it, but this entrance is logically irrelevant because the path used to gain
                            # access to the region will always use a different entrance.
                            # For better performance, it would be best to delete these logically irrelevant
                            # entrances if no other logic depends on them.
                            pass
                        else:
                            stack = traceback.format_stack()
                            # Strip off the `stack = traceback.format_stack()` lines.
                            if "stack = traceback.format_stack()" in stack[-1]:
                                stack = stack[:-2]
                            # Strip off everything before getting to code within this hook. This primarily removes a
                            # bunch of multiprocessing frames.
                            for i, line in enumerate(stack):
                                if "after_generate" in line:
                                    stack = stack[i+1:]
                                    break
                            error_msg = (
                                f"entrance.can_reach for entrance '{last_entrance}' called region.can_reach for region"
                                f" '{r}' without an indirect condition registered."
                                f"\nRegistered indirect conditions for '{r}' are:"
                                f"\n {indirect_conditions}"
                                f"\nThe parent_region of '{last_entrance}' is '{last_entrance.parent_region}'"
                                f"\nThe connected_region of '{last_entrance}' is '{last_entrance.connected_region}'."
                                f"\nTraceback:"
                                f"\n{''.join(stack)}")
                            self.failures.append(error_msg)
            return original(state)

        r.can_reach = region_can_reach_fuzzer_hook_override
