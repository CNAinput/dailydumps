"""Linha de comandos: subcomandos em vez de opções com dois traços."""

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .client import PostgrestClient
from .config import healthcheck_url, load_settings
from .errors import DumpError, IntegrityError, ValidationError
from .health import ping
from .pages import build_pages
from .pending import open_pending_issues, pending_issues, run_gh
from .pipeline import Generator, run_adjust
from .source import Source
from .store import Repo
from .timeutil import last_closed_day, parse_date, parse_timestamp
from .verify import protected_changes, verify_repo


@dataclass
class Context:
    root: Path
    repo: Repo
    environ: dict
    now: datetime
    transport: object
    runner: object
    stdin: object
    out: object


class PtFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "uso: ")


class PtParser(argparse.ArgumentParser):
    """Parser com a ajuda em português."""

    def __init__(self, *args, **kwargs):
        kwargs["formatter_class"] = PtFormatter
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "argumentos"
        self._optionals.title = "opções"
        self.add_argument("-h", action="help", default=argparse.SUPPRESS, help="Mostra esta ajuda e termina.")

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"erro: {message}\n")


def build_parser():
    parser = PtParser(prog="python -m cnadump", description="Arquivo público dos dados diários do mercado da CNA.")
    sub = parser.add_subparsers(dest="command", required=True, title="subcomandos")
    day = sub.add_parser("day", help="Gera os dias fechados em falta, ou apenas a data indicada.")
    day.add_argument("date", nargs="?", help="Data AAAA-MM-DD (opcional).")
    back = sub.add_parser("backfill", help="Gera dias passados, sem snapshots, a partir da data indicada.")
    back.add_argument("date", nargs="?", help="Data inicial AAAA-MM-DD (opcional).")
    regen = sub.add_parser("regenerate", help="Substitui o ficheiro de um dia arquivado e regista-o no manifesto.")
    regen.add_argument("date", help="Data AAAA-MM-DD.")
    sub.add_parser("adjust", help="Regenera daily/ohlc_adjusted.csv a partir do events.csv.")
    sub.add_parser("verify", help="Verifica a integridade do repositório.")
    pending = sub.add_parser("pending", help="Mostra os eventos estruturais por registar.")
    pending.add_argument("action", nargs="?", choices=["open"], help="open: abre as issues com o gh.")
    pages = sub.add_parser("build-pages", help="Gera o site (web/) e a API estática do GitHub Pages.")
    pages.add_argument("folder", nargs="?", default="_site", help="Pasta de saída (por omissão _site).")
    sub.add_parser("guard", help="Lê caminhos do stdin e falha se algum só puder ser escrito pelo workflow.")
    ping_cmd = sub.add_parser("ping", help="Envia o ping ao Healthchecks.io, se HEALTHCHECK_URL estiver definido.")
    ping_cmd.add_argument("status", choices=["ok", "fail"])
    return parser


def warn(ctx, message):
    if ctx.environ.get("GITHUB_ACTIONS") == "true":
        ctx.out(f"::warning::{message}")
    else:
        ctx.out(f"AVISO: {message}")


def generator(ctx):
    settings = load_settings(ctx.root, ctx.environ)
    client = PostgrestClient(settings.url, settings.key, transport=ctx.transport)
    return Generator(ctx.repo, Source(client), ctx.now, log=ctx.out)


def describe_days(days):
    if len(days) <= 5:
        return ", ".join(str(d) for d in days)
    return f"{days[0]} a {days[-1]} ({len(days)} dias)"


def report(ctx, result):
    for message in result.warnings:
        warn(ctx, message)
    if result.days:
        ctx.out(f"Dias gerados: {describe_days(result.days)} ({result.ticks} ticks).")
        if result.snapshot_day:
            ctx.out(f"Snapshot de {result.snapshot_day} guardado.")
        if result.payouts:
            ctx.out(f"Pagamentos de dividendos arquivados: {result.payouts}.")


def cmd_day(args, ctx):
    only = parse_date(args.date) if args.date else None
    report(ctx, generator(ctx).run_day(only))
    if only is None and last_closed_day(ctx.now) not in ctx.repo.price_days():
        raise DumpError("O último dia fechado não ficou arquivado.")
    return 0


def cmd_backfill(args, ctx):
    report(ctx, generator(ctx).run_backfill(parse_date(args.date) if args.date else None))
    return 0


def cmd_regenerate(args, ctx):
    report(ctx, generator(ctx).run_regenerate(parse_date(args.date)))
    return 0


def cmd_adjust(args, ctx):
    run_adjust(ctx.repo, ctx.out)
    return 0


def cmd_verify(args, ctx):
    result = verify_repo(ctx.repo)
    for message in result.warnings:
        warn(ctx, message)
    for message in result.errors:
        ctx.out(f"ERRO: {message}")
    if result.errors:
        return IntegrityError.exit_code
    ctx.out("Repositório íntegro.")
    return 0


def cmd_pending(args, ctx):
    if args.action == "open":
        open_pending_issues(ctx.repo, ctx.runner, ctx.out)
        return 0
    issues = pending_issues(ctx.repo)
    if not issues:
        ctx.out("Não há eventos estruturais por registar.")
    for issue in issues:
        ctx.out(f"{issue.title}\n{issue.body}\n")
    return 0


def cmd_build_pages(args, ctx):
    folder = Path(args.folder)
    target = folder if folder.is_absolute() else ctx.root / folder
    written = build_pages(ctx.repo, target, ctx.now, ctx.environ.get("GITHUB_REPOSITORY"))
    ctx.out(f"Site e API estática gerados ({len(written)} ficheiros).")
    return 0


def cmd_guard(args, ctx):
    blocked = protected_changes(ctx.stdin.read().splitlines())
    for path in blocked:
        ctx.out(f"ERRO: {path}: só o workflow pode alterar este ficheiro (dados de dias passados e derivados).")
    return IntegrityError.exit_code if blocked else 0


def cmd_ping(args, ctx):
    ping(args.status, healthcheck_url(ctx.root, ctx.environ), log=ctx.out)
    return 0


COMMANDS = {
    "day": cmd_day, "backfill": cmd_backfill, "regenerate": cmd_regenerate, "adjust": cmd_adjust,
    "verify": cmd_verify, "pending": cmd_pending, "build-pages": cmd_build_pages, "guard": cmd_guard,
    "ping": cmd_ping,
}


def main(argv=None, root=None, environ=None, now=None, transport=None, runner=None, stdin=None, out=print):
    args = build_parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    if now is None:
        now = parse_timestamp(environ["CNADUMP_NOW"]) if environ.get("CNADUMP_NOW") else datetime.now(timezone.utc)
    ctx = Context(root, Repo(root), environ, now, transport, runner or run_gh, stdin or sys.stdin, out)
    try:
        return COMMANDS[args.command](args, ctx)
    except ValidationError as exc:
        for message in exc.messages:
            out(f"ERRO: {message}")
        return exc.exit_code
    except DumpError as exc:
        out(f"ERRO: {exc}")
        return exc.exit_code
    except ValueError as exc:
        out(f"ERRO: {exc}")
        return 1
