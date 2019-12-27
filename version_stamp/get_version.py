#!/usr/bin/env python3
import argparse
import copy
import sys
import os
import hglib
import logging
import importlib.machinery
import types

sys.path.append('{0}/'.format(os.path.dirname(__file__)))
from ver_stamp import IVersionsStamper
import stamp_utils

LOGGER = logging.getLogger()


def _find_version(versrions_client, name):
    tags = versrions_client.tags()
    root = versrions_client.root()

    for tag in tags:
        if not tag.startswith(name):
            continue

        ver = tag.split('{0}_'.format(name))
        if len(ver) != 2:
            continue

        ver_path = None
        for path in versrions_client.status(tag=tag):
            if not path.endswith(os.sep + 'version.py'):
                continue

            ver_path = path
            break

        if ver_path is None:
            raise RuntimeError(
                'version.py not found for tag {0}. This can be due to a '
                'manual tagging in versions repository. This is not '
                'recommended! Now you can remove all the manual tags '
                'from the versions repository'.format(tag)
            )

        app_ver_path = os.path.join(
            root, *(ver_path.split('/'))
        )

        loader = importlib.machinery.SourceFileLoader(
            'version', app_ver_path)
        mod_ver = types.ModuleType(loader.name)
        try:
            loader.exec_module(mod_ver)
        except FileNotFoundError:
            raise RuntimeError(
                'version.py file not found for tag {0}. '
                'Check how this file might have been '
                'removed'.format(tag[0])
            )

        template = None
        try:
            template = mod_ver.template
        except AttributeError:
            pass

        if template is not None:
            ver_format, octats_count = IVersionsStamper.parse_template(
                template
            )

            return IVersionsStamper.get_formatted_version(
                ver[1], ver_format, octats_count
            )
        else:
            return ver[1]

    return None


def get_version(repos_path, app_name):
    versions_path = stamp_utils.get_versions_repo_path(repos_path)
    versions_client, _ = stamp_utils.get_client(
        versions_path,
        revert=True,
        pull=True
    )

    return _find_version(versions_client, app_name)


def main():
    args = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--repos_path',
        required=True,
        help='The path to the repos base dir for changeset generation'
    )
    parser.add_argument(
        '--app_name', required=True, help="The application's name"
    )

    args = parser.parse_args(args)
    params = copy.deepcopy(vars(args))

    res = get_version(**params)
    print(res, file=sys.stdout)

    if res is None:
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
