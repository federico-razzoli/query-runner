#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Copyright (C) 2024  Federico Razzoli
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""query-runner: Run SQL tests against MariaDB with concurrent connections."""

__version__ = '1.0.0'

import os
import queue
import re
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR  = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.basename(SCRIPT_PATH)

TESTS_DIR = os.path.join(SCRIPT_DIR, 'tests')
ENV_FILE  = os.path.join(SCRIPT_DIR, '.env')

# Exit codes
EXIT_NORMAL    = 1   # normal exit (as specified)
EXIT_ARGS      = 2   # incorrect arguments
EXIT_CONN      = 10  # cannot connect to MariaDB / connection interrupted
EXIT_QUERY_ERR = 11  # at least one query returned an error

# Output indentation
CONN_INDENT   = '  '      # 2 spaces  – connection switch header
QUERY_INDENT  = '    '    # 4 spaces  – query text
RESULT_INDENT = '      '  # 6 spaces  – query results

# ---------------------------------------------------------------------------
# Lazy MariaDB import (so --help/--version work without the package installed)
# ---------------------------------------------------------------------------

_mariadb_module = None


def _get_mariadb():
    """Return the mariadb module, importing it on first call."""
    global _mariadb_module
    if _mariadb_module is None:
        try:
            import mariadb  # noqa: PLC0415
            _mariadb_module = mariadb
        except ImportError:
            print(
                f'{SCRIPT_NAME}: mariadb-connector-python is not installed.\n'
                'Install it with:  pip install mariadb',
                file=sys.stderr,
            )
            sys.exit(EXIT_CONN)
    return _mariadb_module


# ---------------------------------------------------------------------------
# Environment / connection parameters
# ---------------------------------------------------------------------------

def load_env():
    """
    Parse the .env file located next to this script.
    Returns (host, port, user, password).
    """
    params = {}
    try:
        with open(ENV_FILE, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, _, value = line.partition('=')
                    params[key.strip()] = value.strip()
    except FileNotFoundError:
        print(
            f'{SCRIPT_NAME}: .env file not found: {ENV_FILE}',
            file=sys.stderr,
        )
        sys.exit(EXIT_CONN)

    host     = params.get('MARIADB_HOST', 'localhost')
    port     = int(params.get('MARIADB_PORT', '3306'))
    user     = params.get('MARIADB_USER', '').strip()
    password = params.get('MARIADB_PASS', '').strip()
    return host, port, user, password


def make_connection(host, port, user, password):
    """Open and return a new MariaDB connection."""
    mariadb = _get_mariadb()

    localhost = host in ('localhost', '127.0.0.1')
    use_socket_auth = localhost and not user and not password

    connect_args = {}

    if use_socket_auth:
        # UNIX_SOCKET authentication: try common socket paths
        connect_args['user'] = 'root'
        for sock in (
            '/var/run/mysqld/mysqld.sock',
            '/run/mysqld/mysqld.sock',
            '/tmp/mysql.sock',
            '/tmp/mysqld.sock',
        ):
            if os.path.exists(sock):
                connect_args['unix_socket'] = sock
                break
        else:
            # Fall back to TCP on localhost as root with no password
            connect_args['host'] = host
            connect_args['port'] = port
    else:
        connect_args['host'] = host
        connect_args['port'] = port
        connect_args['user'] = user or 'root'
        if password:
            connect_args['password'] = password

    try:
        return mariadb.connect(**connect_args)
    except mariadb.Error as exc:
        print(f'{SCRIPT_NAME}: cannot connect to MariaDB: {exc}', file=sys.stderr)
        sys.exit(EXIT_CONN)


# ---------------------------------------------------------------------------
# Test file parser
# ---------------------------------------------------------------------------

def parse_test_file(filepath):
    """
    Parse a test file into an ordered list of steps.

    Each step is a tuple  (conn_id, queries)  where:
      conn_id  – string identifier from the "#! Connection N" command
      queries  – list of  (display_text, sql, vertical)  tuples
        display_text – original text as written in the file (for printing)
        sql          – text to send to MariaDB (terminator stripped)
        vertical     – True when the terminator was \\G
    """
    with open(filepath, encoding='utf-8') as fh:
        content = fh.read()

    steps = []
    current_conn    = None
    current_queries = []
    pending_lines   = []   # lines accumulating into the next query

    def _flush_query():
        """Save a completed query from pending_lines into current_queries."""
        if not pending_lines:
            return
        display_text = '\n'.join(pending_lines)
        stripped     = display_text.rstrip()

        if stripped.endswith('\\G'):
            sql      = stripped[:-2].rstrip()
            vertical = True
        elif stripped.endswith(';'):
            sql      = stripped[:-1].rstrip()
            vertical = False
        else:
            # Unterminated query – execute as-is, no vertical
            sql      = stripped
            vertical = False

        current_queries.append((display_text, sql, vertical))
        pending_lines.clear()

    for raw_line in content.splitlines():
        stripped = raw_line.strip()

        # Skip blank lines
        if not stripped:
            continue

        # Command line
        if stripped.startswith('#!'):
            cmd_text = stripped[2:].strip()
            cmd      = re.sub(r'\s+', ' ', cmd_text).upper()

            if cmd.startswith('CONNECTION '):
                conn_id = cmd[len('CONNECTION '):].strip()

                # Close off any pending query before switching
                _flush_query()

                # Save the current section (if any)
                if current_conn is not None:
                    if current_queries:
                        steps.append((current_conn, current_queries))
                    current_queries = []

                current_conn = conn_id
            # Other future commands could be handled here
            continue

        # Regular query line
        pending_lines.append(raw_line)

        # Check whether this line ends the current query
        rstripped = stripped.rstrip()
        if rstripped.endswith(';') or rstripped.endswith('\\G'):
            _flush_query()

    # Flush the very last query / section
    _flush_query()
    if current_conn is not None and current_queries:
        steps.append((current_conn, current_queries))

    return steps


# ---------------------------------------------------------------------------
# Output formatting – replicating the mariadb CLI style
# ---------------------------------------------------------------------------

def _fmt_value(val):
    """Render a single cell value as a string."""
    if val is None:
        return 'NULL'
    return str(val)


def format_tabular(columns, rows, elapsed):
    """Format a result set as a pipe-delimited table (default CLI style)."""
    if not rows:
        return f'Empty set ({elapsed:.3f} sec)'

    col_widths = [len(str(c)) for c in columns]
    fmt_rows = []
    for row in rows:
        fmt_row = [_fmt_value(v) for v in row]
        for i, cell in enumerate(fmt_row):
            col_widths[i] = max(col_widths[i], len(cell))
        fmt_rows.append(fmt_row)

    sep    = '+' + '+'.join('-' * (w + 2) for w in col_widths) + '+'
    header = '|' + '|'.join(f' {str(c):<{w}} ' for c, w in zip(columns, col_widths)) + '|'

    lines = [sep, header, sep]
    for fmt_row in fmt_rows:
        lines.append(
            '|' + '|'.join(f' {v:<{w}} ' for v, w in zip(fmt_row, col_widths)) + '|'
        )
    lines.append(sep)

    n = len(rows)
    lines.append(f'{n} row{"s" if n != 1 else ""} in set ({elapsed:.3f} sec)')
    return '\n'.join(lines)


def format_vertical(columns, rows, elapsed):
    """Format a result set in vertical mode (\\G terminator)."""
    if not rows:
        return f'Empty set ({elapsed:.3f} sec)'

    col_width = max(len(str(c)) for c in columns) if columns else 0
    lines = []
    for i, row in enumerate(rows, 1):
        lines.append(f'{"*" * 27} {i}. row {"*" * 27}')
        for col, val in zip(columns, row):
            lines.append(f'{str(col):>{col_width}}: {_fmt_value(val)}')

    n = len(rows)
    lines.append(f'{n} row{"s" if n != 1 else ""} in set ({elapsed:.3f} sec)')
    return '\n'.join(lines)


def format_warnings_table(warnings):
    """Format the output of SHOW WARNINGS as a table."""
    if not warnings:
        return ''
    columns   = ['Level', 'Code', 'Message']
    col_widths = [len(c) for c in columns]
    fmt_rows  = []
    for row in warnings:
        fmt_row = [_fmt_value(v) for v in row]
        for i, cell in enumerate(fmt_row):
            col_widths[i] = max(col_widths[i], len(cell))
        fmt_rows.append(fmt_row)

    sep    = '+' + '+'.join('-' * (w + 2) for w in col_widths) + '+'
    header = '|' + '|'.join(f' {c:<{w}} ' for c, w in zip(columns, col_widths)) + '|'
    lines  = [sep, header, sep]
    for fmt_row in fmt_rows:
        lines.append(
            '|' + '|'.join(f' {v:<{w}} ' for v, w in zip(fmt_row, col_widths)) + '|'
        )
    lines.append(sep)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

def execute_query(cursor, sql, vertical):
    """
    Execute a single SQL statement via *cursor*.

    Returns (output_text, has_error) where output_text is formatted like the
    mariadb CLI client and has_error is True when MariaDB reported an error.
    """
    mariadb = _get_mariadb()
    start   = time.monotonic()

    try:
        cursor.execute(sql)
        elapsed = time.monotonic() - start

        if cursor.description is not None:
            # Result-set query (SELECT, SHOW, EXPLAIN, …)
            columns = [col[0] for col in cursor.description]
            rows    = cursor.fetchall()

            if vertical:
                output = format_vertical(columns, rows, elapsed)
            else:
                output = format_tabular(columns, rows, elapsed)
        else:
            # DML / DDL
            affected = max(cursor.rowcount, 0) if cursor.rowcount is not None else 0
            wc       = getattr(cursor, 'warning_count', 0) or 0

            if wc == 1:
                warn_suffix = ', 1 warning'
            elif wc > 1:
                warn_suffix = f', {wc} warnings'
            else:
                warn_suffix = ''

            output = (
                f'Query OK, {affected} row{"s" if affected != 1 else ""} affected'
                f'{warn_suffix} ({elapsed:.3f} sec)'
            )

        # Append warnings table when present
        wc = getattr(cursor, 'warning_count', 0) or 0
        if wc:
            try:
                cursor.execute('SHOW WARNINGS')
                warnings = cursor.fetchall()
                warn_table = format_warnings_table(warnings)
                if warn_table:
                    output += '\n' + warn_table
            except mariadb.Error:
                pass

        return output, False

    except mariadb.Error as exc:
        elapsed   = time.monotonic() - start
        errno     = getattr(exc, 'errno',     0)      or 0
        sqlstate  = getattr(exc, 'sqlstate',  '00000') or '00000'
        return f'ERROR {errno} ({sqlstate}): {exc}', True


# ---------------------------------------------------------------------------
# Connection worker thread
# ---------------------------------------------------------------------------

class _ConnectionWorker(threading.Thread):
    """
    Daemon thread that owns one MariaDB connection and processes query batches
    sequentially via an internal queue.

    Multiple _ConnectionWorker instances run concurrently – all their
    underlying connections exist at the same time.
    """

    def __init__(self, conn_id, conn):
        super().__init__(daemon=True)
        self.conn_id      = conn_id
        self._conn        = conn
        self._task_queue  = queue.Queue()
        self._result_queue = queue.Queue()

    def run(self):
        cursor = self._conn.cursor()
        while True:
            task = self._task_queue.get()
            if task is None:
                break
            batch_results = []
            for display_text, sql, vertical in task:
                out, err = execute_query(cursor, sql, vertical)
                batch_results.append((display_text, out, err))
            self._result_queue.put(batch_results)
        try:
            cursor.close()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass

    def execute_batch(self, queries):
        """Send a batch of queries and block until results are available."""
        self._task_queue.put(queries)
        return self._result_queue.get()

    def close(self):
        """Signal the worker thread to exit."""
        self._task_queue.put(None)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def _indent_block(text, prefix):
    """Prepend *prefix* to every line in *text*."""
    return '\n'.join(prefix + line for line in text.splitlines())


def run_test(test_path, conn_params):
    """
    Parse and execute a single test file, printing output to stdout.

    Returns (test_name, had_error).
    """
    test_name = os.path.basename(test_path)

    # Print test header: name uppercased and underlined
    print()
    upper_name = test_name.upper()
    print(upper_name)
    print('=' * len(upper_name))

    steps = parse_test_file(test_path)

    if not steps:
        print('  (empty test)')
        return test_name, False

    host, port, user, password = conn_params
    workers    = {}
    had_error  = False

    try:
        for conn_id, queries in steps:
            print(f'{CONN_INDENT}CONNECTION {conn_id}')

            if conn_id not in workers:
                conn   = make_connection(host, port, user, password)
                worker = _ConnectionWorker(conn_id, conn)
                worker.start()
                workers[conn_id] = worker

            results = workers[conn_id].execute_batch(queries)

            for display_text, output, has_error in results:
                if has_error:
                    had_error = True
                print(_indent_block(display_text, QUERY_INDENT))
                print(_indent_block(output, RESULT_INDENT))

    finally:
        for worker in workers.values():
            worker.close()

    return test_name, had_error


# ---------------------------------------------------------------------------
# Test / group discovery
# ---------------------------------------------------------------------------

def _resolve_path(target=None):
    """
    Convert a dot-separated group/test identifier to an absolute path.
    Returns the path, or None when it does not exist.
    """
    if not target:
        return TESTS_DIR
    parts = target.split('.')
    path  = os.path.join(TESTS_DIR, *parts)
    return path if os.path.exists(path) else None


def _sorted_entries(dirpath):
    """Return (groups, files) for *dirpath*, both sorted alphabetically."""
    try:
        entries = sorted(os.listdir(dirpath))
    except PermissionError:
        return [], []
    groups = [e for e in entries if os.path.isdir(os.path.join(dirpath, e))]
    files  = [e for e in entries if os.path.isfile(os.path.join(dirpath, e))]
    return groups, files


def _list_groups(base_path, recursive, indent):
    """Recursively print group names found under *base_path*."""
    groups, _ = _sorted_entries(base_path)
    prefix    = '  ' * indent
    for group in groups:
        print(f'{prefix}{group}')
        if recursive:
            _list_groups(os.path.join(base_path, group), recursive=True, indent=indent + 1)


def _list_tests(base_path, indent):
    """
    Recursively print groups-and-tests tree rooted at *base_path*.
    Groups precede tests at each level; both are sorted alphabetically.
    Only groups that contain at least one test (directly or recursively) are shown.
    """
    groups, files = _sorted_entries(base_path)
    prefix        = '  ' * indent

    for group in groups:
        sub_path = os.path.join(base_path, group)
        sub_groups, sub_files = _sorted_entries(sub_path)
        if sub_files or sub_groups:
            print(f'{prefix}{group}')
            _list_tests(sub_path, indent=indent + 1)

    for fname in files:
        print(f'{prefix}{fname}')


def _collect_tests(base_path):
    """
    Return an ordered list of absolute paths to all test files under
    *base_path* (or *base_path* itself when it is a file).
    Groups precede files; both are sorted alphabetically at every level.
    """
    if os.path.isfile(base_path):
        return [base_path]

    tests = []
    groups, files = _sorted_entries(base_path)

    for group in groups:
        tests.extend(_collect_tests(os.path.join(base_path, group)))
    for fname in files:
        tests.append(os.path.join(base_path, fname))
    return tests


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def _cmd_lsg(args):
    """lsg [-r] [GROUP]"""
    recursive = False
    rest      = list(args)

    if rest and rest[0] == '-r':
        recursive = True
        rest.pop(0)

    group = rest.pop(0) if rest else None

    if rest:
        print(f'{SCRIPT_NAME}: lsg: unexpected argument: {rest[0]}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    base = _resolve_path(group)
    if base is None:
        print(f'{SCRIPT_NAME}: group not found: {group}', file=sys.stderr)
        sys.exit(EXIT_ARGS)
    if not os.path.isdir(base):
        print(f'{SCRIPT_NAME}: not a group: {group}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    _list_groups(base, recursive=recursive, indent=0)
    sys.exit(EXIT_NORMAL)


def _cmd_lst(args):
    """lst [GROUP]"""
    group = args[0] if args else None

    if len(args) > 1:
        print(f'{SCRIPT_NAME}: lst: unexpected argument: {args[1]}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    base = _resolve_path(group)
    if base is None:
        print(f'{SCRIPT_NAME}: group not found: {group}', file=sys.stderr)
        sys.exit(EXIT_ARGS)
    if not os.path.isdir(base):
        print(f'{SCRIPT_NAME}: not a group: {group}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    _list_tests(base, indent=0)
    sys.exit(EXIT_NORMAL)


def _cmd_cat(args):
    """cat <TEST | GROUP>"""
    if not args:
        print(f'{SCRIPT_NAME}: cat: expected a test or group', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    if len(args) > 1:
        print(f'{SCRIPT_NAME}: cat: unexpected argument: {args[1]}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    target = args[0]
    path   = _resolve_path(target)

    if path is None:
        print(f'{SCRIPT_NAME}: not found: {target}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    if os.path.isfile(path):
        # Single test: print content without a header
        with open(path, encoding='utf-8') as fh:
            print(fh.read(), end='')
    else:
        # Group: print each test with a header
        test_files = _collect_tests(path)
        first = True
        for test_path in test_files:
            rel     = os.path.relpath(test_path, TESTS_DIR)
            test_id = rel.replace(os.sep, '.')
            upper   = test_id.upper()

            if not first:
                print()
            first = False

            print(upper)
            print('=' * len(upper))

            with open(test_path, encoding='utf-8') as fh:
                print(fh.read(), end='')

    sys.exit(EXIT_NORMAL)


def _cmd_run(args):
    """run [GROUP | TEST]"""
    target = args[0] if args else None

    if len(args) > 1:
        print(f'{SCRIPT_NAME}: run: unexpected argument: {args[1]}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    base = _resolve_path(target)
    if base is None:
        print(f'{SCRIPT_NAME}: not found: {target}', file=sys.stderr)
        sys.exit(EXIT_ARGS)

    conn_params = load_env()
    test_files  = _collect_tests(base)

    if not test_files:
        print('No tests found.')
        sys.exit(EXIT_NORMAL)

    had_any_error = False
    test_count    = 0

    for test_path in test_files:
        _, err = run_test(test_path, conn_params)
        test_count += 1
        if err:
            had_any_error = True

    print()
    print(f'{test_count} test{"s" if test_count != 1 else ""} executed')

    sys.exit(EXIT_QUERY_ERR if had_any_error else EXIT_NORMAL)


# ---------------------------------------------------------------------------
# --help / --version
# ---------------------------------------------------------------------------

_HELP = f"""\
Usage: {SCRIPT_NAME} COMMAND [OPTIONS]

Commands:
  lsg [-r] [GROUP]   List groups (first level by default; -r for recursive)
  lst [GROUP]        Show groups and their tests
  run [GROUP|TEST]   Run all tests, or tests in a group, or a single test
  cat <TEST|GROUP>   Print the source of a test, or of all tests in a group

Options:
  --help             Show this help message and exit
  --version          Show version information and exit

GROUP and TEST use dot-separated hierarchies, e.g.:
  group1.subgroup.another
  group1.subgroup.test_name

Tests directory: {TESTS_DIR}
"""


def _print_help():
    print(_HELP, end='')
    sys.exit(0)


def _print_version():
    print(f'query-runner {__version__}')
    sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if not args or args[0] in ('--help', '-h'):
        _print_help()

    if args[0] in ('--version', '-V'):
        _print_version()

    cmd      = args[0]
    cmd_args = args[1:]

    if cmd == 'lsg':
        _cmd_lsg(cmd_args)
    elif cmd == 'lst':
        _cmd_lst(cmd_args)
    elif cmd == 'cat':
        _cmd_cat(cmd_args)
    elif cmd == 'run':
        _cmd_run(cmd_args)
    else:
        print(
            f'{SCRIPT_NAME}: unknown command: {cmd}\n'
            f"Try '{SCRIPT_NAME} --help' for more information.",
            file=sys.stderr,
        )
        sys.exit(EXIT_ARGS)


if __name__ == '__main__':
    main()
