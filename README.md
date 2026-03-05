# query-runner

**query-runner** is a Python CLI tool that executes SQL test files against a
MariaDB database and prints results in the same format as the `mariadb` CLI
client. Tests are plain text files that interleave SQL statements across
multiple named database connections, enabling concurrent-connection scenarios
such as transaction isolation and lock contention testing.

---

## Setup

### Prerequisites

- Python 3.8 or newer
- A running MariaDB instance
- `mariadb-connector-python`:

```bash
pip install mariadb
```

### Connection Configuration

The tool reads connection parameters from a `.env` file located in the same
directory as `run.py`. A template is provided:

```bash
cp .env.template .env
```

Edit `.env` and fill in your connection details:

```
MARIADB_HOST=localhost
MARIADB_PORT=3306
MARIADB_USER=
MARIADB_PASS=
```

**UNIX socket shortcut**: when `MARIADB_HOST` is `localhost` or `127.0.0.1`
*and* both `MARIADB_USER` and `MARIADB_PASS` are empty, the tool automatically
connects as `root` using the UNIX socket authentication plugin (no password
required). This is convenient for local development on most Linux systems.

---

## Usage

```
python run.py COMMAND [OPTIONS]
```

### Commands

| Command | Description |
|---------|-------------|
| `lsg [-r] [GROUP]` | List groups. Shows the first level by default; use `-r` for recursive listing. Optionally scope to a specific GROUP. |
| `lst [GROUP]` | Show groups and their tests. Optionally scope to a specific GROUP. |
| `run [GROUP\|TEST]` | Run all tests, all tests in a GROUP, or a single TEST. |

GROUP and TEST names use dot-separated hierarchies corresponding to the
directory structure under `tests/`, for example:

```
group1.subgroup.another        ← a group
group1.subgroup.test_name      ← a test
```

### Options

| Option | Description |
|--------|-------------|
| `--help`, `-h` | Show help message and exit (exit code 0) |
| `--version`, `-V` | Show version information and exit (exit code 0) |

### Examples

```bash
# List all top-level groups
python run.py lsg

# List all groups recursively
python run.py lsg -r

# List groups and their tests
python run.py lst

# List tests inside a specific group
python run.py lst basic

# Run all tests
python run.py run

# Run all tests in a group
python run.py run basic

# Run a single test
python run.py run basic.simple_queries
```

### Output Format

Results are printed to stdout in the same style as the `mariadb` CLI client:

| Situation | Output |
|-----------|--------|
| SELECT with rows | Pipe-delimited table + `N rows in set (T sec)` |
| SELECT with no rows | `Empty set (T sec)` |
| DML / DDL | `Query OK, N rows affected (T sec)` |
| Statement with warnings | DML line followed by a `SHOW WARNINGS` table |
| Error | `ERROR N (SQLSTATE): message` |
| Query ending with `\G` | Vertical key: value format |

Output is indented to visually separate connections:

```
  CONNECTION 1                   ← 2 spaces
    SELECT 1;                    ← 4 spaces (query text)
      +---+                      ← 6 spaces (result lines)
      | 1 |
      +---+
      1 row in set (0.001 sec)
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | `--help` or `--version` (follows standard Linux CLI conventions) |
| 1 | Normal exit after a successful `lsg`, `lst`, or `run` |
| 2 | Incorrect arguments |
| 10 | Cannot connect to MariaDB, or connection dropped during a test |
| 11 | At least one query returned an error |

---

## How To Create a Test

### Test File Format

A test is a plain text file placed anywhere inside the `tests/` directory.
It contains SQL statements separated by `#! Connection N` command lines that
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

**Rules:**

- Lines starting with `#!` are commands (case-insensitive, extra whitespace
  ignored). The only supported command is `Connection N`.
- Empty lines are ignored.
- Everything else—including SQL comments—is treated as a query.
- A query ends with `;` (tabular output) or `\G` (vertical output).
- Each `Connection N` identifier gets its own dedicated MariaDB connection.
  All connections for a test are open simultaneously.

### Groups

Groups are simply subdirectories inside `tests/`. Nesting is supported—a
subdirectory inside a group is a sub-group.

```
tests/
├── basic/               ← group "basic"
│   ├── simple_queries   ← test "basic.simple_queries"
│   └── vertical_format  ← test "basic.vertical_format"
└── transactions/        ← group "transactions"
    └── concurrent_transactions  ← test "transactions.concurrent_transactions"
```

### Creating a New Test

1. Choose a name and decide which group (directory) it belongs to. Create a
   new group directory if needed.
2. Create the test file:

   ```bash
   # Example: a new test in the "basic" group
   touch tests/basic/my_new_test
   ```

3. Write the test content using the format shown above.

4. Verify the test appears in the listing:

   ```bash
   python run.py lst basic
   ```

5. Run the test:

   ```bash
   python run.py run basic.my_new_test
   ```

---

## AI-Related Files

This repository contains two files specifically intended to guide AI coding
agents:

### AGENTS.md

Provides guidance for AI agents working on this codebase: project overview,
repository layout, key concepts, output format, exit codes, connection
parameters, development notes, and usage examples. Read this file before
making changes to the codebase.

### DOUBTS.md

Records open questions and design decisions that arose from ambiguities in the
original specification. Topics include the rationale for exit code `1` on
normal success, the behaviour of concurrent connections and potential
deadlocks, test file naming conventions, and more. Consult this file when
the intended behaviour is unclear.

---

## License

query-runner is free software released under the
[GNU Affero General Public License v3.0 or later](LICENSE)
(SPDX: `AGPL-3.0-or-later`).
