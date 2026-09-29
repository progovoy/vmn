"""``vmn-exp lineage <app> -v <ref> [--depth N] [--json]``: the runs a run
consumed from and fed, and the model versions registered from it."""
from vmn_exp.cli.views import dumps
from vmn_exp.sdk.reader import get_lineage
from version_stamp.api import VMN_LOGGER


def _node_line(node, app_name):
    label = node["verstr"] if node["app"] == app_name else f"{node['app']}:{node['verstr']}"
    details = [node.get("name"), node.get("status"), None if node["found"] else "missing"]
    extra = "  ".join(d for d in details if d)
    hops = f"  (depth {node['depth']})" if node["depth"] > 1 else ""
    return f"    {label}  {extra}{hops}".rstrip()


def _print_nodes(title, nodes, app_name):
    if not nodes:
        print(f"  {title} none")
        return
    print(f"  {title.rstrip()}")
    for node in nodes:
        print(_node_line(node, app_name))
        for link in node["links"]:
            print(f"        {link['input']} <- {link['artifact']} ({link['via']})")


def _print_models(models):
    if not models:
        return
    print("  Models:")
    for m in models:
        aliases = f" [{', '.join(m['aliases'])}]" if m["aliases"] else ""
        print(f"    {m['model']} v{m['version']}{aliases}  {m['status']}")


def experiment_lineage(storage, app_name, args):
    ref = (getattr(args, "version", None) or ["latest"])[0]
    try:
        lineage = get_lineage(
            app_name, ref, storage=storage, depth=getattr(args, "depth", None) or 1
        )
    except ValueError as e:
        VMN_LOGGER.error(str(e))
        return 1
    if getattr(args, "json", False):
        print(dumps(lineage))
        return 0
    print(f"Lineage: {lineage['verstr']}")
    _print_nodes("Upstream:  ", lineage["upstream"], app_name)
    _print_nodes("Downstream:", lineage["downstream"], app_name)
    _print_models(lineage["models"])
    if lineage["truncated"]:
        print("  (truncated: more linked runs than shown)")
    return 0
