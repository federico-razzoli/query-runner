# AGENTS.md

This file provides guidance for AI coding agents working on this codebase.

## Project Overview

**query-runner** is a Python CLI tool that executes SQL test files against a
MariaDB database and prints results in the same format as the `mariadb` CLI
client.  Tests are plain text files that interleave SQL statements across
multiple named database connections, enabling concurrent-connection scenarios
such as transaction isolation and lock contention testing.

## Repository Layout

```
run.py              Main CLI script (single file, no external dependencies
                    beyond mariadb-connector-python)
tests/              Test files and groups (subdirectories = groups)
.env                MariaDB credentials – NOT versioned (see .gitignore)
.env.template       Template to create .env from
AGENTS.md           This file
DOUBTS.md           Open questions about the specification
LICENSE             GNU Affero General Public License v3
```

## Key Concepts

### Test files

Every file anywhere inside `tests/` is a test.  Sub-directories are *groups*.
A test file contains SQL statements separated by `#! Connection N` command
lines that switch the active database connection:

```
#! Connection 1

START TRANSACTION;
SELECT 1;

#! Connection 2

SELECT 2;

#! Connection 1

COMMIT;
```

- Lines beginning with `#!` are commands (case-insensitive, extra spaces
  ignored).
- Empty lines are ignored.
- Everything else—including SQL comments—is treated as a query.
- Queries end with `;` (tabular output) or `\G` (vertical output).

### Concurrent connections

Each `Connection N` identifier gets its own `_ConnectionWorker` thread and a
dedicated MariaDB connection.  All connections for a test are open
simultaneously.  Steps execute in the order they appear in the file; the main
thread waits for each batch to complete before dispatching the next one.

### Output format

Results are printed to stdout in the same style as the `mariadb` CLI client:

| Situation           | Output                                        |
|---------------------|-----------------------------------------------|
| SELECT rows         | pipe-delimited table + "N rows in set (T sec)"|
| SELECT empty        | "Empty set (T sec)"                           |
| DML / DDL           | "Query OK, N rows affected (T sec)"           |
| Warnings            | DML line amended + SHOW WARNINGS table        |
| Error               | "ERROR N (SQLSTATE): message"                 |
| `\G` terminator     | vertical key: value format                    |

### Indentation

```
  CONNECTION 1                   ← 2 spaces
    SELECT 1;                    ← 4 spaces (query text)
      +---+                      ← 6 spaces (result lines)
      | 1 |
      +---+
      ...
```

## Exit Codes

| Code | Meaning                                         |
|------|-------------------------------------------------|
|  1   | Normal exit (successful run, listing, etc.)     |
|  2   | Incorrect arguments                             |
| 10   | Cannot connect to MariaDB / connection dropped  |
| 11   | At least one query returned an error            |

Note: `--help` and `--version` exit with **0** following Linux conventions.

## Connection Parameters (.env)

Copy `.env.template` to `.env` and fill in the values:

```
MARIADB_HOST=localhost
MARIADB_PORT=3306
MARIADB_USER=
MARIADB_PASS=
```

When `MARIADB_HOST` is `localhost` or `127.0.0.1` **and** both `MARIADB_USER`
and `MARIADB_PASS` are empty, `run.py` connects as `root` using the
UNIX_SOCKET authentication plugin (no password required).

## Development Notes

- **Language**: Python 3.8+
- **Only external dependency**: `mariadb-connector-python` (`pip install mariadb`)
- The `mariadb` module is imported lazily so that `--help` and `--version`
  work even without the package installed.
- Always refer to the database as **MariaDB** (never MySQL).
- The `tests/` directory path is resolved relative to `run.py`, not to the
  current working directory, so the script can be run from any directory.
- SPDX license identifier `AGPL-3.0-or-later` must appear in every source
  file header.

## Running the Tool

```bash
# List all top-level groups
python run.py lsg

# List all groups recursively
python run.py lsg -r

# List groups and their tests
python run.py lst

# Run all tests
python run.py run

# Run a specific group
python run.py run basic

# Run a specific test
python run.py run basic.simple_queries
```
