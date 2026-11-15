"""The writer id and run suffix of the process's real environment and host, for
tests that call a writer helper the way production's roots do (plan 44 G12):
resolved at the call, as the helpers once resolved them themselves."""
from vmn_exp.core.real_io import real_io
from vmn_exp.core.writer import default_run_suffix, get_writer_id


def process_writer():
    io = real_io()
    return get_writer_id(io.env, io.host)


def process_suffix():
    io = real_io()
    return default_run_suffix(io.env, io.host)
