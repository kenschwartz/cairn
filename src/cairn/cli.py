import argparse
import sys

from cairn.commands.init import run_init
from cairn.commands.doctor import run_doctor
from cairn.commands.new import run_new


def main():
    parser = argparse.ArgumentParser(prog="cairn")
    parser.add_argument("--version", action="version", version="cairn 1.0.0")
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

    args = parser.parse_args()

    if args.command == "init":
        return run_init(args)
    elif args.command == "doctor":
        return run_doctor(args)
    elif args.command == "new":
        return run_new(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
