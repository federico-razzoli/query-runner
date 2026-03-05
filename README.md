# query-runner

**query-runner** is a Python CLI tool that executes SQL test files against a
MariaDB database and prints results in the same format as the `mariadb` CLI
client.  Test files can interleave SQL statements across multiple named database
connections, enabling concurrent-connection scenarios such as transaction
isolation and lock contention testing.

## Setup

### Prerequisites

- Python 3.8 or later
- MariaDB server
- [mariadb-connector-python](https://pypi.org/project/mariadb/): `pip install mariadb`

### Connection configuration (.env)

`run.py` reads connection parameters from a `.env` file located in the same
directory as the script.  Copy `.env.template` to `.env` and fill in the
values:

```bash
cp .env.template .env
```

The template contains:

```
MARIADB_HOST=localhost
MARIADB_PORT=3306
MARIADB_USER=
MARIADB_PASS=
```

When `MARIADB_HOST` is `localhost` or `127.0.0.1` **and** both `MARIADB_USER`
and `MARIADB_PASS` are left empty, `run.py` connects as `root` using the
UNIX_SOCKET authentication plugin (no password required).  This is convenient
for local development on Linux systems.

For remote or password-protected instances, fill in all four variables.

## Usage

```
python run.py COMMAND [OPTIONS]
```

### Commands

| Command | Syntax | Description |
|---------|--------|-------------|
| `lsg` | `lsg [-r] [GROUP]` | List groups. Shows top-level groups by default; use `-r` for a recursive listing. An optional `GROUP` argument narrows the scope. |
| `lst` | `lst [GROUP]` | List groups and the tests they contain. An optional `GROUP` argument narrows the scope. |
| `run` | `run [GROUP\|TEST]` | Run tests. Without arguments all tests are run. Pass a group name to run that group, or a test name to run a single test. |

### Flags

| Flag | Description |
|------|-------------|
| `--help`, `-h` | Show help and exit (exit code 0) |
| `--version`, `-V` | Show version and exit (exit code 0) |

### Dot-separated identifiers

Groups and tests are identified with dot-separated paths mirroring the
directory hierarchy under `tests/`.  For example:

```bash
# List all top-level groups
python run.py lsg

# List groups recursively
python run.py lsg -r

# List groups and tests inside a specific group
python run.py lst transactions

# Run all tests
python run.py run

# Run all tests in a group
python run.py run basic

# Run a single test
python run.py run basic.simple_queries
```

### Output format

Results are printed to stdout in the same style as the `mariadb` CLI client:

| Situation | Output |
|-----------|--------|
| SELECT with rows | Pipe-delimited table followed by `N rows in set (T sec)` |
| SELECT with no rows | `Empty set (T sec)` |
| DML / DDL | `Query OK, N rows affected (T sec)` |
| Statement with warnings | DML line amended with warning count + `SHOW WARNINGS` table |
| Error | `ERROR N (SQLSTATE): message` |
| `\G` terminator | Vertical `key: value` format |

Output is indented to show which connection produced each result:

```
  CONNECTION 1                   ← 2 spaces
    SELECT 1;                    ← 4 spaces (query text)
      +---+                      ← 6 spaces (result lines)
      | 1 |
      +---+
      1 row in set (0.000 sec)
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | `--help` or `--version` |
| 1 | Normal exit (successful run, listing, etc.) |
| 2 | Incorrect arguments |
| 10 | Cannot connect to MariaDB, or connection dropped |
| 11 | At least one query returned an error |

## How To Create a Test

### Test file format

A test file is a plain text file placed anywhere inside the `tests/` directory.
Every regular file inside `tests/` is treated as a test, regardless of name or
extension.

The file contains SQL statements and `#! Connection N` command lines that
switch the active database connection:

```sql
#! Connection 1

START TRANSACTION;
SELECT 'connection 1 started a transaction';

#! Connection 2

START TRANSACTION;
SELECT 'connection 2 started a transaction';

#! Connection 1

ROLLBACK;

#! Connection 2

ROLLBACK;
```

Rules:

- Lines beginning with `#!` are commands (case-insensitive, extra spaces
  ignored).
- Empty lines are ignored.
- Everything else—including SQL comments (`--`, `/* */`)—is treated as a query.
- Queries end with `;` (tabular output) or `\G` (vertical output).

### Concurrent connections

Each unique `Connection N` identifier gets its own dedicated MariaDB connection,
and all connections for a test are open simultaneously.  Steps execute in the
order they appear in the file; the runner waits for each step to complete before
moving to the next one.

> **Note:** If a query on one connection would block waiting for a lock held by
> another connection, make sure the *releasing* step appears in the file
> *before* the blocking step.  Otherwise the script will hang.

### Groups

Sub-directories of `tests/` are **groups** and can be nested to any depth.
Use groups to organize related tests:

```
tests/
  basic/
    simple_queries
    vertical_format
  transactions/
    concurrent_transactions
```

### Calling a test

After creating a test file, run it by passing its dot-separated path to the
`run` command:

```bash
# File at tests/basic/my_new_test
python run.py run basic.my_new_test

# File at tests/transactions/isolation/repeatable_read
python run.py run transactions.isolation.repeatable_read
```

To run all tests in a group:

```bash
python run.py run basic
```

Use `lst` to verify that the new test is visible:

```bash
python run.py lst
```

## AI-Related Files

This repository contains two files intended as guidance for AI coding agents:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Provides an overview of the project, key concepts, output format, exit codes, connection parameters, and development notes for AI agents working on the codebase. |
| `DOUBTS.md` | Records open questions and design decisions that arose from ambiguities in the original specification, along with the rationale for each choice made. |

These files are not required for normal use of the tool.

## License

query-runner is free software released under the
[GNU Affero General Public License v3.0 or later](https://www.gnu.org/licenses/agpl-3.0.html)
(SPDX: `AGPL-3.0-or-later`).

See the [LICENSE](LICENSE) file for the full license text.