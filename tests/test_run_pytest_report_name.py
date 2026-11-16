"""run_pytest.sh names its HTML reports after the -k expression. A long
--specific_test still gets a file name the filesystem accepts (255 bytes),
while short ones keep the readable name they always had."""
import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parent / "run_pytest.sh"
NAME_MAX = 255


def _suffix(suite, specific_test):
    """html_report_suffix from the sourced script, as the runner computes it."""
    result = subprocess.run(
        ["bash", "-c", 'source "$1" && html_report_suffix "$2" "$3"', "_", str(SCRIPT),
         suite, specific_test],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _serial_report(suffix):
    return f"report_{suffix}_serial.html"


def test_no_filter_names_the_report_all():
    assert _suffix("core", "none") == "core_all"


def test_short_expressions_keep_their_readable_name():
    assert _suffix("exp", "test_a or test_b") == "exp_test_a_or_test_b"
    assert _suffix("core", "test_x[1-2].y") == "core_test_x_1-2_.y"


def test_a_long_expression_fits_the_file_name_limit():
    expr = " or ".join(f"test_number_{i}" for i in range(200))
    name = _serial_report(_suffix("exp", expr))
    assert len(name.encode()) <= NAME_MAX, len(name.encode())
    assert name.startswith("report_exp_test_number_0_or_test_number_1_or_")


def test_a_long_non_ascii_expression_fits_the_file_name_limit():
    name = _serial_report(_suffix("exp", "é" * 1000))
    assert len(name.encode()) <= NAME_MAX, len(name.encode())


def test_a_long_expression_gets_the_same_name_every_time():
    expr = "x" * 2000
    assert _suffix("core", expr) == _suffix("core", expr)


def test_long_expressions_that_share_a_prefix_get_distinct_names():
    prefix = "test_" * 100
    assert _suffix("core", prefix + "a") != _suffix("core", prefix + "b")


def test_the_longest_readable_name_is_kept_and_one_more_byte_is_hashed():
    # report_ + core_ + expr + _serial.html = 255 bytes at most
    fits = "a" * (NAME_MAX - len("report_core__serial.html"))
    assert _suffix("core", fits) == "core_" + fits
    hashed = _suffix("core", fits + "a")
    assert hashed != "core_" + fits + "a"
    assert len(_serial_report(hashed).encode()) <= NAME_MAX
