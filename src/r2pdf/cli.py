"""
r2pdf CLI — Command-line interface for the r2pdf converter.
"""

import argparse
import logging
import sys
from pathlib import Path

from r2pdf.converter import (
    DEFAULT_LIBRARY,
    DEFAULT_OUTPUT,
    ConversionError,
    FileValidationError,
    OutputValidationError,
    convert_bulk,
    convert_single,
)


def setup_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="r2pdf",
        description=(
            "Convert EPUB files to dark-mode, double-spaced PDFs "
            "optimized for the Remarkable Paper Pro."
        ),
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        metavar="INPUT",
        help=(
            "Single EPUB file, or directory for bulk mode. "
            f"Defaults to {DEFAULT_LIBRARY} (entire library)."
        ),
    )
    parser.add_argument(
        "-o", "--output",
        default=str(DEFAULT_OUTPUT),
        metavar="DIR",
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "-b", "--bulk",
        action="store_true",
        help="Treat INPUT as directory and process all books recursively.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="Parallel workers for bulk conversion (default: 4).",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=11,
        metavar="N",
        help="Base font size in pt (default: 11).",
    )
    parser.add_argument(
        "--line-height",
        type=float,
        default=2.0,
        metavar="F",
        help="Line height multiplier, unitless — scales with font size (default: 2.0).",
    )
    parser.add_argument(
        "--margin",
        type=int,
        default=None,
        metavar="MM",
        help="Set all four page margins (in mm). Overrides individual --margin-* flags.",
    )
    parser.add_argument(
        "--margin-top",
        type=int,
        default=15,
        metavar="MM",
        help="Top padding inside the page in mm (default: 15).",
    )
    parser.add_argument(
        "--margin-bottom",
        type=int,
        default=15,
        metavar="MM",
        help="Bottom padding inside the page in mm (default: 15).",
    )
    parser.add_argument(
        "--margin-left",
        type=int,
        default=10,
        metavar="MM",
        help="Left padding inside the page in mm (default: 10).",
    )
    parser.add_argument(
        "--margin-right",
        type=int,
        default=10,
        metavar="MM",
        help="Right padding inside the page in mm (default: 10).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files that already have an output PDF.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be converted without actually converting.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug output.",
    )
    return parser


def main() -> int:
    parser = setup_argparse()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    _all = args.margin
    options = {
        "workers": args.workers,
        "font_size": args.font_size,
        "line_height": args.line_height,
        "margin_top":    _all if _all is not None else args.margin_top,
        "margin_bottom": _all if _all is not None else args.margin_bottom,
        "margin_left":   _all if _all is not None else args.margin_left,
        "margin_right":  _all if _all is not None else args.margin_right,
        "skip_existing": args.skip_existing,
        "dry_run": args.dry_run,
    }

    output_dir = Path(args.output).expanduser().resolve()

    if args.input is None:
        input_path = DEFAULT_LIBRARY
    else:
        input_path = Path(args.input).expanduser().resolve()

    if input_path.is_dir() or args.bulk:
        if not input_path.is_dir():
            logging.getLogger(__name__).error("INPUT is not a directory: %s", input_path)
            return 1
        stats = convert_bulk(input_path, output_dir, options)
        print(
            f"\nDone. Total: {stats['total']} | "
            f"Converted: {stats['converted']} | "
            f"Skipped: {stats['skipped']} | "
            f"Failed: {stats['failed']}"
        )
        return 0 if stats["failed"] == 0 else 2

    else:
        if not input_path.exists():
            logging.getLogger(__name__).error("Input file not found: %s", input_path)
            return 1
        try:
            out = convert_single(input_path, output_dir, options)
            if not args.dry_run:
                print(f"Output: {out}")
            return 0
        except (FileValidationError, ConversionError, OutputValidationError) as e:
            logging.getLogger(__name__).error("%s", e)
            return 1


if __name__ == "__main__":
    sys.exit(main())
