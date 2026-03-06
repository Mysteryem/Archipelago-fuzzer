"""
This hook recursively replaces global lists and dicts with immutable list/dict subclasses.
It also recursively replaces any lists/dicts found within tuples.

WARNING: This hook is a work-in-progress and is not production-ready.
"""

from copy import deepcopy

from fuzz import BaseHook, GenOutcome


# I wanted to use collections.UserList and collections.UserDict, but they don't inherit from list/dict, so are not json
# serializable. Be aware that inheriting from list/dict is more prone to unexpected issues.


class HookMutationFailureException(Exception):
    pass


class ImmutableList(list):
    def __setitem__(self, i, item):
        raise HookMutationFailureException("__setitem__ is not allowed")

    def __delitem__(self, i):
        raise HookMutationFailureException("__delitem__ is not allowed")

    def append(self, item):
        raise HookMutationFailureException("append is not allowed")

    def __iadd__(self, other):
        raise HookMutationFailureException("__iadd__ is not allowed")

    def insert(self, i, item):
        raise HookMutationFailureException("insert is not allowed")

    def pop(self, i=-1):
        raise HookMutationFailureException("pop is not allowed")

    def remove(self, item):
        raise HookMutationFailureException("remove is not allowed")

    def copy(self):
        # Escape the immutable list
        return list(self)

    def __copy__(self):
        # Escape the immutable list
        return list(self)

    def __deepcopy__(self, memodict=...):
        return deepcopy(self.copy(), memodict)

    def sort(self, *, key=None, reverse=False):
        raise HookMutationFailureException("sort is not allowed")

    def extend(self, other):
        raise HookMutationFailureException("extend is not allowed")

    def clear(self):
        raise HookMutationFailureException("clear is not allowed")

    def reverse(self):
        raise HookMutationFailureException("reverse is not allowed")

    def extend_internal(self, other):
        super().extend(other)


class ImmutableDict(dict):

    def setdefault(self, __key, __default=None):
        raise HookMutationFailureException("setdefault is not allowed")

    def update(self, __m, **kwargs):
        raise HookMutationFailureException("update is not allowed")

    def __setitem__(self, key, item):
        raise HookMutationFailureException("__setitem__ is not allowed")

    def __delitem__(self, key):
        raise HookMutationFailureException("__delitem__ is not allowed")

    def copy(self):
        # Escape the immutable dict
        return dict(self)

    def __copy__(self):
        # Escape the immutable dict
        return dict(self)

    def __deepcopy__(self, memodict=...):
        return deepcopy(self.copy(), memodict)

    def __ior__(self, other):
        raise HookMutationFailureException("__ior__ is not allowed")

    def pop(self, __key):
        raise HookMutationFailureException("pop is not allowed")

    def popitem(self):
        raise HookMutationFailureException("popitem is not allowed")

    def clear(self):
        raise HookMutationFailureException("clear is not allowed")

    def update_internal(self, other):
        super().update(other)


def recursive_replace(v, memodict = None):
    # Most of this mess is just to support handling lists/dicts that contain themselves.
    if type(v) is list:
        v_id = id(v)
        if memodict is None:
            # No memodict.
            replacement = ImmutableList()
            memodict = {v_id: replacement}
        elif v_id in memodict:
            # Already been replaced.
            return memodict[v_id]
        else:
            # memodict exists, but does not contain `v`
            replacement = ImmutableList()
            memodict[v_id] = replacement

        replacement.extend_internal(recursive_replace(v2, memodict) for v2 in v)
        return replacement
    elif type(v) is dict:
        v_id = id(v)
        if memodict is None:
            # No memodict.
            replacement = ImmutableDict()
            memodict = {v_id: replacement}
        elif v_id in memodict:
            # Already been replaced.
            return memodict[v_id]
        else:
            # memodict exists, but does not contain `v`
            replacement = ImmutableDict()
            memodict[v_id] = replacement

        replacement.update_internal(zip(v.keys(), (recursive_replace(v2, memodict) for v2 in v.values())))
        return replacement
    elif type(v) is tuple:
        # A tuple is immutable, so it's not possible to put a tuple inside itself (at least in normal Python code).
        # There could, however, by mutable types within the tuple, and a tuple can be fairly safely replaced with a new
        # tuple.
        if memodict is None:
            memodict = {}
        return tuple(recursive_replace(v2, memodict) for v2 in v)
    else:
        return v


class Hook(BaseHook):
    @staticmethod
    def test_immutable_list():
        normal_list = [1, 3, 2]
        immutable_list = recursive_replace(normal_list)

        try:
            immutable_list[0] = 4
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for __setitem__")

        try:
            del immutable_list[0]
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for __delitem__")

        try:
            immutable_list.append(4)
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for append")

        try:
            immutable_list += [4]
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for += (__iadd__)")

        try:
            immutable_list.insert(2, 4)
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for insert")

        try:
            immutable_list.pop(0)
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for pop")

        try:
            immutable_list.remove(1)
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for remove")

        try:
            immutable_list.sort()
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for sort")

        try:
            immutable_list.extend([4])
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for extend")

        try:
            immutable_list.clear()
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for clear")

        try:
            immutable_list.reverse()
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for reverse")

        if immutable_list.copy() != normal_list or immutable_list.copy() != [1, 3, 2]:
            raise Exception("Immutable list was modified")

    @staticmethod
    def test_immutable_dict():
        normal_dict = {1: "1", 2: "2", 3: "3"}
        immutable_dict = recursive_replace(normal_dict)

        try:
            immutable_dict.setdefault(4, "4")
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for setdefault")

        try:
            immutable_dict.update({4: "4"})
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for update")

        try:
            immutable_dict[4] = "4"
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for __setitem__")

        try:
            del immutable_dict[1]
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for __delitem__")

        try:
            immutable_dict |= {4: "4"}
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for |= (__ior__)")

        try:
            immutable_dict.pop(2)
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for pop")

        try:
            immutable_dict.popitem()
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for popitem")

        try:
            immutable_dict.clear()
        except HookMutationFailureException:
            pass
        else:
            raise Exception("Exception not raised for clear")

        if immutable_dict.copy() != normal_dict or immutable_dict.copy() != {1: "1", 2: "2", 3: "3"}:
            raise Exception("Immutable list was modified")

    def setup_main(self, args):
        super().setup_main(args)
        self.test_immutable_list()
        self.test_immutable_dict()

    def setup_worker(self, args):
        super().setup_worker(args)
        from worlds import AutoWorld
        import importlib
        for world_type in AutoWorld.AutoWorldRegister.world_types.values():
            # Replace globals in the world's module.
            world_module = importlib.import_module(world_type.__module__)
            for k, v in vars(world_module).copy().items():
                if k.startswith("__"):
                    continue
                replacement = recursive_replace(v)
                if replacement is not v:
                    setattr(world_module, k, replacement)
            # Replace class attributes on the World class.
            for k, v in world_type.__dict__.copy().items():
                if k.startswith("__"):
                    continue
                replacement = recursive_replace(v)
                if replacement is not v:
                    setattr(world_type, k, replacement)

    def reclassify_outcome(self, outcome, raised):
        if outcome != GenOutcome.Success and not isinstance(raised, HookMutationFailureException):
            # Ignore other errors.
            return GenOutcome.OptionError, None
        else:
            return super().reclassify_outcome(outcome, raised)
