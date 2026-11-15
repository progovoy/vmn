"""Count direct IO in a Python module's source, by kind (the IO ratchet's scanner).

``scan(source)`` resolves ``import x as y`` and ``from x import y [as z]`` and
then counts, per kind:

- calls to a known IO function (``time.monotonic()``, ``open()``, ...);
- loads of an IO object (``os.environ``, ``sys.stdout``);
- ``real_default``: a parameter defaulting to an IO function or object
  (``def f(clock=time.time)``);
- ``clock_alias``: a module-level name bound to a time function
  (``_now = time.time``).

Calls through an injected object (``self._clock()``, ``sleep(1)`` on a
parameter) are not counted, and neither is a seeded ``random.Random(seed)``.

Blind spots, by design: ``pathlib.Path`` methods (``p.exists()``) cannot be
typed statically, so ``fs`` counts os/open/shutil/tempfile/fcntl/glob calls
only; ``Event.wait(timeout)``/``Condition.wait(timeout)`` and
``asyncio.sleep`` are not recognisable by name and stay outside the ratchet.
"""
import ast
import builtins
import shutil
import tempfile
from collections import Counter

_KINDS = {
    "time": (
        "time.time time.time_ns time.monotonic time.monotonic_ns time.perf_counter "
        "time.perf_counter_ns time.process_time time.process_time_ns time.thread_time "
        "time.sleep datetime.datetime.now datetime.datetime.utcnow "
        "datetime.datetime.today datetime.date.today"
    ),
    "env": "os.getenv os.putenv os.unsetenv os.getenvb",
    "process_self": (
        "os.getpid os.getppid os.kill os.killpg os.getpgid os.getpgrp os.setsid "
        "os.setpgrp os.getuid os.geteuid os._exit socket.gethostname platform.node"
    ),
    "fs": (
        "builtins.open io.open os.open os.fdopen os.fsync os.listdir os.scandir os.walk "
        "os.stat os.lstat os.makedirs os.mkdir os.remove os.unlink os.rmdir "
        "os.removedirs os.rename os.renames os.replace os.link os.symlink os.readlink "
        "os.chmod os.chown os.utime os.access os.truncate os.statvfs os.getcwd os.chdir "
        "os.path.exists os.path.lexists os.path.isfile os.path.isdir os.path.islink "
        "os.path.getsize os.path.getmtime os.path.getctime os.path.getatime "
        "os.path.realpath os.path.samefile glob.glob glob.iglob fcntl.flock fcntl.lockf"
    ),
    "subprocess": (
        "subprocess.run subprocess.Popen subprocess.call subprocess.check_call "
        "subprocess.check_output subprocess.getoutput subprocess.getstatusoutput "
        "os.system os.popen os.fork os.execv os.execve os.execvp os.execvpe "
        "os.spawnv os.spawnvp os.posix_spawn os.posix_spawnp asyncio.create_subprocess_exec "
        "asyncio.create_subprocess_shell multiprocessing.Process"
    ),
    "random": (
        "uuid.uuid1 uuid.uuid4 os.urandom random.random random.randint random.randrange "
        "random.choice random.choices random.shuffle random.sample random.uniform "
        "random.gauss random.getrandbits random.SystemRandom secrets.token_hex "
        "secrets.token_bytes secrets.token_urlsafe secrets.choice secrets.randbelow "
        "secrets.randbits"
    ),
    "net": (
        "socket.socket socket.create_connection socket.create_server "
        "socket.getaddrinfo urllib.request.urlopen http.client.HTTPConnection "
        "http.client.HTTPSConnection smtplib.SMTP requests.get requests.post "
        "requests.put requests.delete requests.request requests.Session httpx.Client "
        "httpx.AsyncClient boto3.client boto3.resource boto3.session.Session"
    ),
    "sqlite": "sqlite3.connect",
    "thread": (
        "threading.Thread threading.Timer _thread.start_new_thread "
        "concurrent.futures.ThreadPoolExecutor concurrent.futures.ProcessPoolExecutor"
    ),
    "console": "builtins.print builtins.input getpass.getpass",
}


def _public_functions(module):
    """Every public callable of *module* except its exception classes."""
    return [
        f"{module.__name__}.{name}"
        for name in module.__all__
        if not (isinstance(getattr(module, name), type)
                and issubclass(getattr(module, name), BaseException))
    ]


CALLS = {name: kind for kind, names in _KINDS.items() for name in names.split()}
CALLS.update((name, "fs") for name in _public_functions(shutil) + _public_functions(tempfile))
# Objects that are IO wherever they are loaded, called or not.
OBJECTS = {"os.environ": "env", "os.environb": "env",
           "sys.stdout": "console", "sys.stderr": "console", "sys.stdin": "console"}
_UNSEEDED = {"random.Random"}  # IO only when built without a seed


def scan(source):
    """``Counter[kind]`` of the direct IO in *source* (see the module docstring)."""
    tree = ast.parse(source)
    resolve = _resolver(_aliases(tree))
    counts = Counter()
    defaults = _count_real_defaults(tree, resolve, counts)
    _count_clock_aliases(tree, resolve, counts)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kind = _call_kind(node, resolve(node.func))
        elif isinstance(node, (ast.Name, ast.Attribute)) and id(node) not in defaults:
            kind = OBJECTS.get(resolve(node))
        else:
            kind = None
        if kind:
            counts[kind] += 1
    return counts


def _call_kind(call, name):
    if name in _UNSEEDED:
        return "random" if not (call.args or call.keywords) else None
    return CALLS.get(name)


def _aliases(tree):
    """Local name -> dotted origin, from every import in the module."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    found[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    found[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                found[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return found


def _resolver(aliases):
    def resolve(node):
        if isinstance(node, ast.Name):
            if node.id in aliases:
                return aliases[node.id]
            return f"builtins.{node.id}" if hasattr(builtins, node.id) else None
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    return resolve


def _is_io_reference(node, resolve):
    name = resolve(node) if isinstance(node, (ast.Name, ast.Attribute)) else None
    return name in CALLS or name in OBJECTS


def _count_real_defaults(tree, resolve, counts):
    """Count IO defaults; return their node ids so they are not counted twice."""
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for default in node.args.defaults + node.args.kw_defaults:
                if default is not None and _is_io_reference(default, resolve):
                    counts["real_default"] += 1
                    seen.add(id(default))
    return seen


def _count_clock_aliases(tree, resolve, counts):
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, (ast.Name, ast.Attribute)) and CALLS.get(resolve(value)) == "time":
            counts["clock_alias"] += 1
