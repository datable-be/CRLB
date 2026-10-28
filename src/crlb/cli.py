"""The `crlb` command: one subcommand per action of the pipeline."""

import argparse
from types import ModuleType

from crlb.database import build
from crlb.ocr import analyse_specimens, sample_specimens


def add_command(
    commands: argparse._SubParsersAction, name: str, module: ModuleType
) -> None:
    """Add a subcommand whose help comes from the module docstring and whose arguments come from its configure()."""
    module.configure(
        commands.add_parser(
            name,
            help=(module.__doc__ or "").splitlines()[0],
            description=module.__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(prog="crlb", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    add_command(commands, "build", build)

    ocr = commands.add_parser("ocr", help="OCR quality test on specimen pages")
    ocr_commands = ocr.add_subparsers(dest="ocr_command", required=True)
    for name, module in (("sample", sample_specimens), ("analyse", analyse_specimens)):
        add_command(ocr_commands, name, module)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the chosen command."""
    args = build_parser().parse_args(argv)
    args.func(args)
