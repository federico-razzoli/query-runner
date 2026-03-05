# DOUBTS.md

This file records questions and design decisions that arose from ambiguities in
the specification.

---

## 1. Exit code for normal execution

The specification states: *"The exit code should normally be 1."*

This is contrary to the POSIX/Linux convention where exit code `0` means
success.  This implementation follows the specification literally—commands
(`lsg`, `lst`, `run`) exit with code `1` on success.

However, `--help` and `--version` exit with `0`, in keeping with nearly
universal Linux CLI conventions for those two flags.  If `1` is also required
for them, change `_print_help()` and `_print_version()` to call `sys.exit(1)`.

---

## 2. Blocking queries and concurrent execution

The specification requires that *"connections must actually be concurrent."*

This implementation opens every connection in a dedicated Python thread, so
all connections for a test exist simultaneously.  Steps (batches of SQL
belonging to one connection) execute in the order they appear in the test file;
the main thread waits for each batch to finish before starting the next.

**Consequence**: if a query on Connection 2 blocks waiting for a lock held by
Connection 1, and Connection 1's next batch (e.g. `COMMIT`) is defined *after*
Connection 2's batch in the file, the script will deadlock.  To test lock
contention you must order the steps so that the releasing connection acts
*before* any step that would block, or accept that the script will hang and
require manual interruption.

If truly interleaved concurrent execution (without waiting for each step) is
required, the execution engine would need to be redesigned to dispatch all
steps asynchronously and collect results after all connections complete.

---

## 3. Test file naming / extensions

The specification says *"each file in this directory is a test"* without
mentioning file extensions.  This implementation treats every regular file
inside `tests/` as a test, regardless of extension (or absence thereof).

If a specific extension (e.g. `.sql`) is required, filter files in
`_sorted_entries()` accordingly.

---

## 4. Which groups appear in `lst`

The specification says `lst` should *"list groups that contain tests, and for
each of them, list tests."*  This implementation shows a recursive tree where
every group that has at least one test anywhere in its subtree is shown,
together with all directly contained tests.  Groups with no test files anywhere
beneath them are omitted.

---

## 5. Underline character for test names

The specification says the test name should be *"underlined with ASCII
characters"* without specifying which character.  This implementation uses `=`
(the RST "title" underline), which is visually prominent.  Change the character
in `run_test()` if `=` is not the desired choice.

---

## 6. UNIX socket path

When host is `localhost` / `127.0.0.1` and no credentials are provided, the
implementation tries several common socket paths:

- `/var/run/mysqld/mysqld.sock`
- `/run/mysqld/mysqld.sock`
- `/tmp/mysql.sock`
- `/tmp/mysqld.sock`

If none of those paths exist it falls back to a TCP connection as `root`
without a password.  Add a `MARIADB_UNIX_SOCKET` variable to `.env.template`
if a configurable path is needed.

---

## 7. Warnings display

After any statement that produces warnings, this implementation automatically
executes `SHOW WARNINGS` and appends the result table.  This mirrors the
`mariadb` CLI's behaviour when `--show-warnings` is active.  If warnings
should only be shown on explicit request, wrap the `SHOW WARNINGS` call behind
an option flag.
