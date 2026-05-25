import argparse

from foxport.cli import build_parser


def _all_help_text(parser: argparse.ArgumentParser):
    yield parser.format_help()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                yield from _all_help_text(subparser)


def test_cli_help_text_is_ascii_safe_for_legacy_windows_consoles():
    parser = build_parser()
    for help_text in _all_help_text(parser):
        help_text.encode("ascii")
