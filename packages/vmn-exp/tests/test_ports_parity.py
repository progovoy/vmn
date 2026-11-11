"""vmn_exp.core.ports duplicates version_stamp.core.ports (the SDK may not
import version_stamp). The ports both sides share must keep the same methods
and signatures; the vmn-exp-only ones are listed here, so a new difference
fails until it is either removed or listed."""
import inspect
from typing import Protocol

from version_stamp.core import ports as vmn_ports
from vmn_exp.core import ports as exp_ports

VMN_EXP_ONLY = {"Host", "Processes.popen"}


def _protocols(module):
    return {
        name: cls
        for name, cls in vars(module).items()
        if inspect.isclass(cls) and Protocol in cls.__mro__[1:] and cls.__module__ == module.__name__
    }


def _methods(cls):
    """The methods written in the class body (not the ``__init__`` Protocol adds)."""
    return {
        name: inspect.signature(fn)
        for name, fn in vars(cls).items()
        if inspect.isfunction(fn) and fn.__qualname__.startswith(f"{cls.__qualname__}.")
    }


def _names(module):
    names = set()
    for port, cls in _protocols(module).items():
        names.add(port)
        names |= {f"{port}.{method}" for method in _methods(cls)}
    return names


def test_shared_ports_have_the_same_methods_and_signatures_in_both_packages():
    exp, vmn = _protocols(exp_ports), _protocols(vmn_ports)
    for port in vmn.keys() & exp.keys():
        exp_methods, vmn_methods = _methods(exp[port]), _methods(vmn[port])
        shared = {m: s for m, s in exp_methods.items() if f"{port}.{m}" not in VMN_EXP_ONLY}
        assert shared == vmn_methods, port


def test_shared_ports_take_plan_35s_shapes():
    """docs/plans/35-core-io-behind-interfaces.md, Design 1."""
    for module in (vmn_ports, exp_ports):
        assert set(_methods(module.Clock)) == {"now", "monotonic", "sleep"}
        assert str(inspect.signature(module.Clock.sleep)) == "(self, sec: 'float') -> 'None'"
        assert str(inspect.signature(module.Processes.run)) == (
            "(self, cmd: 'Sequence[str]', **kwargs: 'Any') -> 'subprocess.CompletedProcess | None'"
        )
        assert set(_methods(module.Console)) == {"out", "err", "read_line"}


def _outermost(names):
    return {name for name in names if name.split(".")[0] == name or name.split(".")[0] not in names}


def test_vmn_exp_only_ports_are_exactly_the_listed_ones():
    assert _outermost(_names(exp_ports) - _names(vmn_ports)) == VMN_EXP_ONLY
    assert _names(vmn_ports) - _names(exp_ports) == set()
