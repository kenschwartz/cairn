import argparse
import sys

from cairn.commands.init import run_init
from cairn.commands.doctor import run_doctor
from cairn.commands.new import run_new
from cairn.commands.capture import run_capture
from cairn.commands.validate import run_validate
from cairn.commands.remote import run_remote
from cairn.commands.search import run_search
from cairn.commands.dashboard import run_dashboard
from cairn.commands.rename import run_rename
from cairn.commands.reindex import run_reindex
from cairn.commands.tags import run_tags
from cairn.commands.tag import run_tag
from cairn.commands.asset import run_asset


def main():
    parser = argparse.ArgumentParser(prog="cairn")
    parser.add_argument("--version", action="version", version="cairn 1.1.1")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("path", nargs="?", default=".")

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--fix", action="store_true")

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("title", nargs="?")
    new_parser.add_argument("--type", default="note")
    new_parser.add_argument("--tag", action="append")
    new_parser.add_argument("--project", default="")

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("text", nargs="?")
    capture_parser.add_argument("--file")
    capture_parser.add_argument("--title")
    capture_parser.add_argument("--tag", action="append")
    capture_parser.add_argument("--project", default="")
    capture_parser.add_argument("--moc", default="")
    capture_parser.add_argument("--source", default="")
    capture_parser.add_argument("--source-url", default="")

    validate_parser = subparsers.add_parser("validate")

    remote_parser = subparsers.add_parser("remote")
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command")
    remote_add_parser = remote_subparsers.add_parser("add")
    remote_add_parser.add_argument("url")
    remote_add_parser.add_argument("--name")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query", nargs="*")
    search_parser.add_argument("--tag", action="append")
    search_parser.add_argument("--type")
    search_parser.add_argument("--status")
    search_parser.add_argument("--project")

    subparsers.add_parser("dashboard")

    rename_parser = subparsers.add_parser("rename")
    rename_parser.add_argument("path")
    rename_parser.add_argument("title")

    subparsers.add_parser("reindex")

    tags_parser = subparsers.add_parser("tags")

    tag_parser = subparsers.add_parser("tag")
    tag_subparsers = tag_parser.add_subparsers(dest="tag_command")
    tag_rename_parser = tag_subparsers.add_parser("rename")
    tag_rename_parser.add_argument("old")
    tag_rename_parser.add_argument("new")
    tag_remove_parser = tag_subparsers.add_parser("remove")
    tag_remove_parser.add_argument("tag")

    asset_parser = subparsers.add_parser("asset")
    asset_subparsers = asset_parser.add_subparsers(dest="asset_command")
    asset_add_parser = asset_subparsers.add_parser("add")
    asset_add_parser.add_argument("path")
    asset_add_parser.add_argument("--note")
    asset_add_parser.add_argument("--large", action="store_true")
    asset_add_parser.add_argument("--source-url")

    args = parser.parse_args()

    if args.command == "init":
        return run_init(args)
    elif args.command == "doctor":
        return run_doctor(args)
    elif args.command == "new":
        return run_new(args)
    elif args.command == "capture":
        return run_capture(args)
    elif args.command == "validate":
        return run_validate(args)
    elif args.command == "remote":
        return run_remote(args)
    elif args.command == "search":
        return run_search(args)
    elif args.command == "dashboard":
        return run_dashboard(args)
    elif args.command == "rename":
        return run_rename(args)
    elif args.command == "reindex":
        return run_reindex(args)
    elif args.command == "tags":
        return run_tags(args)
    elif args.command == "tag":
        return run_tag(args)
    elif args.command == "asset":
        return run_asset(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
