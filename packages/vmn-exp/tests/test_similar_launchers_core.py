"""The entrypoint of a launched command (vmn_exp.core.similar_profile): a
distributed launcher run as ``python -m <launcher>`` or as its own executable
is looked past, to the script or program it starts."""
import pytest
from similar_fixtures import run
from vmn_exp.core.similar_profile import build_profile, entrypoint, profile_tokens
from vmn_exp.core.similar_score import score


@pytest.mark.parametrize("command, expected", [
    (["python", "-m", "torch.distributed.run", "--nproc_per_node", "8", "train.py", "fit"],
     ("train.py", ("fit",))),
    (["python", "-m", "torch.distributed.launch", "--nproc_per_node=8", "train.py"],
     ("train.py", ())),
    (["python3", "-m", "accelerate.commands.launch", "--num_processes", "2", "src/train.py",
      "--lr", "1"], ("train.py", ("--lr", "1"))),
    (["python", "-m", "deepspeed.launcher.runner", "--num_gpus", "2", "train.py"],
     ("train.py", ())),
    (["python", "-m", "torch.distributed.run", "--nproc_per_node", "8", "-m", "pkg.train",
      "fit"], ("pkg.train", ("fit",))),
    (["python", "-m", "torch.distributed.run", "--no-python", "./bench"], ("bench", ())),
    (["python", "-m", "pdb", "train.py"], ("train.py", ())),
    ("python -m torch.distributed.run --nproc_per_node 8 train.py fit", ("train.py", ("fit",))),
])
def test_a_launcher_module_is_looked_past_to_the_script_it_starts(command, expected):
    assert entrypoint(command) == expected


def test_a_launcher_module_with_nothing_to_launch_is_the_entrypoint_itself():
    assert entrypoint(["python", "-m", "torch.distributed.run", "--help"]) == (
        "torch.distributed.run", ("--help",))


@pytest.mark.parametrize("command, expected", [
    (["python", "-m", "pkg.train", "fit"], ("pkg.train", ("fit",))),
    (["python", "-m", "pkg.train", "--", "x"], ("pkg.train", ("--", "x"))),
    (["mytool", "--", "arg"], ("mytool", ("--", "arg"))),
    (["mytool", "--flag", "value"], ("mytool", ("--flag", "value"))),
])
def test_a_plain_module_or_program_keeps_its_name(command, expected):
    assert entrypoint(command) == expected


@pytest.mark.parametrize("command, expected", [
    (["torchrun", "--nproc_per_node", "8", "src/train.py", "fit"], ("train.py", ("fit",))),
    (["accelerate", "launch", "--config_file", "cfg.yaml", "train.py", "--lr", "1"],
     ("train.py", ("--lr", "1"))),
    (["deepspeed", "--num_gpus", "2", "train.py", "--deepspeed", "ds.json"],
     ("train.py", ("--deepspeed", "ds.json"))),
    (["mpirun", "-np", "4", "./a.out", "--size", "8"], ("a.out", ("--size", "8"))),
    (["srun", "-p", "gpu", "--", "./bench", "x"], ("bench", ("x",))),
    (["srun", "-N", "2", "-p", "gpu", "hostname"], ("hostname", ())),
    (["mpirun", "--hostfile", "hosts", "./bench"], ("bench", ())),
    (["mpiexec", "-n", "2", "--host", "a,b", "./bench", "-q"], ("bench", ("-q",))),
    (["srun", "--exclusive", "hostname"], ("hostname", ())),
])
def test_a_launcher_executable_starts_the_program_after_its_own_options(command, expected):
    assert entrypoint(command) == expected


def _launched(script):
    return {"row": run("r", commit="ccccccc", base="9.0.0"),
            "command": ["python", "-m", "torch.distributed.run", "--nproc_per_node", "8",
                        script, "fit"]}


def test_two_distributed_launches_of_other_scripts_share_no_entrypoint():
    signals = score(_launched("train.py"), _launched("eval.py"))[2]
    assert signals["entrypoint"] == 0.0
    assert score(_launched("train.py"), _launched("train.py"))[2]["entrypoint"] == 1.0


def test_the_index_token_names_the_launched_script():
    view = _launched("train.py")
    profile = build_profile(view["row"], command=view["command"])
    assert "cmd:train.py" in profile_tokens(profile)
    assert "cmd:torch.distributed.run" not in profile_tokens(profile)
