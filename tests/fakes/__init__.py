"""In-memory fakes of the IO ports (``version_stamp.core.ports`` and
``vmn_exp.core.ports``), shared by both test suites.

Plain classes that import neither package (the core suite makes ``vmn_exp``
unimportable). Each one passes the same contract test as its real class:
packages/vmn-exp/tests/unit/test_ports_contract.py.
"""
