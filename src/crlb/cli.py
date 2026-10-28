"""The `crlb` command: one subcommand per action of the pipeline."""

import argparse
from types import ModuleType

from crlb import set_active
from crlb.correction import correct, lexicon, measure, show
from crlb.database import build
from crlb.ocr import analyse_specimens, sample_specimens
from crlb.segmentation import entries, segment
from crlb.segmentation import show as segment_show


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
    add_command(commands, "lexicon", lexicon)

    correction = commands.add_parser(
        "correct", help="OCR correction (step 2a) and its measurement"
    )
    correction_commands = correction.add_subparsers(
        dest="correct_command", required=True
    )
    for name, module in (("run", correct), ("measure", measure), ("show", show)):
        add_command(correction_commands, name, module)

    segmentation = commands.add_parser(
        "segment", help="segmentation (step 3) and its review"
    )
    segment_commands = segmentation.add_subparsers(
        dest="segment_command", required=True
    )
    add_command(segment_commands, "run", segment)
    add_command(segment_commands, "show", segment_show)
    add_command(segment_commands, "entries", entries)

    add_command(commands, "set-active", set_active)

    ocr = commands.add_parser("ocr", help="OCR quality test on specimen pages")
    ocr_commands = ocr.add_subparsers(dest="ocr_command", required=True)
    for name, module in (("sample", sample_specimens), ("analyse", analyse_specimens)):
        add_command(ocr_commands, name, module)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the chosen command."""
    args = build_parser().parse_args(argv)
    args.func(args)
