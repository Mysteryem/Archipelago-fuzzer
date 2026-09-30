# Hook to test that game datapackages remain static throughout generations.
# Fails when:
# - The datapackage is nondeterministic.
# - The datapackage has changed after generation is complete.
# - A world has set any of the datapackage ClassVar attributes onto the world instance.
# - The datapackage in the output multidata does not match the world's class' datapackage.

import zipfile
from argparse import Namespace
from copy import deepcopy
from typing import Container

from BaseClasses import MultiWorld
from MultiServer import Context
from worlds import AutoWorld, network_data_package

from fuzz import BaseHook, GenOutcome

class HookTestFailure(Exception):
    pass


_DATA_PACKAGE_ATTRIBUTES = (
    "item_name_groups",
    "item_name_to_id",
    "location_name_groups",
    "location_name_to_id",
)


def get_other_process_game_data_packages():
    """Run on another process to check for game data packages being nondeterministic."""
    return network_data_package["games"]


class Hook(BaseHook):

    # A deepcopy is made so that it is impossible for worlds to keep reference to anything mutable within the dict.
    _expected_game_data_packages = deepcopy(network_data_package["games"])
    _nondeterministic_game_data_package_checksums: Container[str] = ()
    _nondeterministic_game_data_packages: Container[str] = ()
    _error_message: str = ""
    _output_expected: bool = False

    def setup_main(self, args: Namespace):
        super().setup_main(args)

        # Retrieve the game data packages from another Python process, to check for datapackages that are being
        # constructed in a nondeterministic manner.
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing
        # ProcessPoolExecutor is used to make it easier to pass data between processes and to handle exceptions.
        # "spawn" is used to ensure the new process gets its own PYTHONHASHSEED.
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
            game_data_packages_from_other_process = executor.submit(
                get_other_process_game_data_packages).result(timeout=20)
        nondeterministic_checksum_failures = set()
        nondeterministic_full_failures = set()
        for game_name, game_data_package in self._expected_game_data_packages.items():
            if game_data_packages_from_other_process[game_name] != game_data_package:
                nondeterministic_checksum_failures.add(game_name)
                # Additionally check if the checksum only differs because the dicts have different orders.
                no_checksum_package_from_other_process = game_data_packages_from_other_process[game_name].copy()
                del no_checksum_package_from_other_process["checksum"]
                no_checksum_package = game_data_package.copy()
                del no_checksum_package["checksum"]
                if no_checksum_package_from_other_process != no_checksum_package:
                    nondeterministic_full_failures.add(game_name)
        # An exception could be raised here when there are nondeterministic datapackages, but this could include
        # datapackages for games that are not currently being fuzzed. Instead, the results are stored and then the hook
        # later raises an Exception during generation if one of the games being fuzzed has a nondeterministic
        # datapackage.
        # `setup_main` runs on the main process only, so anything set onto `self` during `setup_main` is not accessible
        # by worker processes. Instead, it is necessary to set them onto the `args`, which are passed to each worker
        # process.
        args.nondeterministic_game_data_package_checksums = nondeterministic_checksum_failures
        args.nondeterministic_game_data_packages = nondeterministic_full_failures

    def setup_worker(self, args: Namespace):
        super().setup_worker(args)
        self._nondeterministic_game_data_package_checksums = args.nondeterministic_game_data_package_checksums
        self._nondeterministic_game_data_packages = args.nondeterministic_game_data_packages
        self._error_message = ""
        self._output_expected = not args.skip_output
        assert self._expected_game_data_packages

        # Raise a HookTestFailure if one of the games in the multiworld has a nondeterministic datapackage.
        # The multiworld does not exist yet, and it is difficult to determine what games will be in the multiworld, so
        # a method that is called early during generation is monkey-patched to perform this check.

        # set_options is run at an early part of generation, and is easy to intercept with monkeypatching.
        set_options_original = MultiWorld.set_options

        def set_options_replacement(mw: MultiWorld, args):
            for game in sorted(set(mw.game.values())):
                # Since set_options is run in part of generation, the fuzzer hook will catch any exceptions raised.
                if game in self._nondeterministic_game_data_packages:
                    raise HookTestFailure(
                        f"The game datapackage for {game} has nondeterministic contents, this is a critical bug.")
                if game in self._nondeterministic_game_data_package_checksums:
                    raise HookTestFailure(
                        f"The game datapackage for {game} has a nondeterministic order of its contents and therefore"
                        f" has a nondeterministic checksum. This needlessly uses up server storage space for each"
                        f" unique datapackage checksum.")
            # Call the original method.
            set_options_original(mw, args)

        MultiWorld.set_options = set_options_replacement

    def after_generate(self, mw: MultiWorld, output_path: str):
        super().after_generate(mw, output_path)

        for game_name, world_type in AutoWorld.AutoWorldRegister.world_types.items():
            data_package_data = world_type.get_data_package_data()
            if data_package_data != self._expected_game_data_packages[game_name]:
                self._error_message = (f"Datapackage mismatch for game '{game_name}' after generation. The datapackage"
                                       f" has probably been modified during generation. The datapackage should be set"
                                       f" once during world *class* initialization and then should never change.")
                return

        if mw is None:
            # Some other generation error occured, resulting in no multiworld.
            return

        # Check that datapackage attributes have not been set on the world *instance*. This usually indicates a
        # misunderstanding of Archipelago implementations.
        for world in mw.worlds.values():
            for attribute_name in _DATA_PACKAGE_ATTRIBUTES:
                if getattr(world, attribute_name) is not getattr(type(world), attribute_name):
                    self._error_message = (f"Datapackage attribute '{attribute_name}' has been defined on the world"
                                           f" instance. This is likely an error, the datapackage attributes should"
                                           f" only be set on the world class itself.")
                    return

        # The remaining checks are run against the output multidata, which won't exist if output was skipped.
        if not self._output_expected:
            return

        # Check that the game datapackages written into the multidata match the worlds (an apworld has been seen
        # changing their game datapackage in the multidata during modify_multidata).

        # Load the output multidata.
        with zipfile.ZipFile(output_path+"/AP_"+mw.seed_name+".zip") as zf:
            for file in zf.namelist():
                if file.endswith(".archipelago"):
                    compressed_multidata = zf.read(file)
                    break
            else:
                self._error_message = "No .archipelago found in archive, something is very wrong."
                return
        multidata = Context.decompress(compressed_multidata)

        # Compare the multidata game datapackages against what is expected.
        if "datapackage" not in multidata:
            self._error_message = '"datapackage" is missing from output multidata, something is very wrong.'
            return
        datapackages_from_multidata = multidata.get("datapackage", {})
        for game_name, game_data_package in datapackages_from_multidata.items():
            if game_data_package != self._expected_game_data_packages[game_name]:
                self._error_message = (f"Output multidata datapackage mismatch for game '{game_name}', the datapackage"
                                       f" should be set during world class initialization and then should never change")
                return

    def reclassify_outcome(self, outcome: GenOutcome, raised: BaseException | None):
        # Report failure if the error message has been set.
        if self._error_message:
            return GenOutcome.Failure, HookTestFailure(self._error_message)
        # Propagate a HookTestFailure raised during generation.
        if isinstance(raised, HookTestFailure):
            return super().reclassify_outcome(outcome, raised)
        # Ignore any other non-success.
        if outcome != GenOutcome.Success:
            return GenOutcome.OptionError, raised
        # Propagate success.
        return super().reclassify_outcome(outcome, raised)

