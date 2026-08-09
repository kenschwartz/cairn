import argparse
import sys

from cairn.commands.init import run_init
from cairn.commands.doctor import run_doctor
from cairn.commands.new import run_new
from cairn.commands.capture import run_capture
from cairn.commands.validate import run_validate
from cairn.commands.remote import run_remote


def main():
    parser = argparse.ArgumentParser(prog="cairn")
    parser.add_argument("--version", action="version", version="cairn 1.0.1")
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
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
