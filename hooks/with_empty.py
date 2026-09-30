from fuzz import BaseHook
from BaseClasses import Item, Location, ItemClassification, Region
from worlds.AutoWorld import WebWorld, World
from worlds import network_data_package, AutoWorldRegister
import os
import tempfile


_GAME_NAME = "FuzzerEmpty"


class Hook(BaseHook):
    def setup_main(self, args):
        self._tmp = tempfile.TemporaryDirectory(prefix="apfuzz")
        with open(os.path.join(self._tmp.name, "empty.yaml"), "w") as fd:
            fd.write(f"""name: Player{{number}}
description: Empty world to weed restrictive starts out
game: {_GAME_NAME}
{_GAME_NAME}: {{}}
""")
        args.with_static_worlds = self._tmp.name

    def setup_worker(self, args):
        if _GAME_NAME not in AutoWorldRegister.world_types:
            # Similar setup to `test.general.TestWorld`.
            class EmptyWebWorld(WebWorld):
                tutorials = []

            # The metaclass handles registration into AutoWorldRegister when the class is created.
            class EmptyWorld(World):
                game = _GAME_NAME
                item_name_to_id = {"Goal Macguffin": 999} | {f"Filler Item {i+1}": i+1 for i in range(99)}
                location_name_to_id = {f"Location {i+1}": i+1 for i in range(100)}
                hidden = True
                web = EmptyWebWorld()

                def create_item(self, name: str) -> Item:
                    item_id = self.item_name_to_id[name]
                    return Item(
                        name,
                        ItemClassification.progression if name == "Goal Macguffin" else ItemClassification.filler,
                        item_id,
                        self.player,
                    )

                def create_items(self) -> None:
                    self.multiworld.itempool.extend(map(self.create_item, self.item_name_to_id))

                def create_regions(self) -> None:
                    # Create 100 locations in the origin region that are accessible from the start.
                    origin = Region(self.origin_region_name, self.player, self.multiworld)
                    self.multiworld.regions.append(origin)
                    origin.add_locations(
                        self.location_name_to_id,
                        Location,
                    )

                def set_rules(self) -> None:
                    self.multiworld.completion_condition[self.player] = lambda state: state.has(
                        "Goal Macguffin", self.player
                    )

            network_data_package["games"][EmptyWorld.game] = EmptyWorld.get_data_package_data()

        if _GAME_NAME not in AutoWorldRegister.world_types:
            raise RuntimeError("Empty world failed to register")