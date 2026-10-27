# psql

## What it is

**`psql`** is PostgreSQL's interactive command-line client. You type SQL and see the results as text tables. It is a program separate from the server: it connects over the network (or inside the container) exactly like any other client. It also reads SQL from a file or from standard input, and it has its own commands, called **meta-commands**, that start with a backslash.

## Why this repository uses it

`psql` is how SQL files reach the database from `make`: `make db` pipes three files into it. It runs inside the database container, so no PostgreSQL client has to be installed on your machine. CI uses a `psql` that comes with the GitHub runner.

## Where it appears

| File | Use |
|---|---|
| `Makefile` | The `PSQL` variable, and the targets `db`, `reset`, `psql`. |
| `.github/workflows/ci.yml` | Overrides `PSQL` with a local `psql`. |
| `sql/002_seed.sql`, `sql/003_queries.sql` | Contain psql meta-commands (`\gset`, `\if`, `\endif`, `\o`). |
| `src/busy_listing/infrastructure/sql_script.py` | Skips those lines when Python runs a file. |

## How it works underneath

**Connecting.** `psql -h host -p port -U user -d database` (`-h` host, `-p` port, `-U` user name, `-d` database name). The password comes from the `PGPASSWORD` environment variable, a password file, or a prompt. Inside the database's container the defaults (local socket) work.

**Giving it input.** Interactively, by typing. With `-c "SQL"`, one command. With `-f file`, or with the file redirected into standard input (`psql ... < file.sql`).

**Options used in this repository.**

- `-X`: do not read the user's `~/.psqlrc` start-up file, so results do not depend on personal settings.
- `-q`: quiet; skip the informational messages (like `CREATE TABLE`).
- `-v ON_ERROR_STOP=1`: sets the psql variable `ON_ERROR_STOP`; with it, psql stops at the first error and exits with a non-zero code (3), instead of carrying on with the rest of the file. Without it, a failing statement is reported but the script continues and the exit code is 0.
- `-U user -d database`: whom to connect as and to what.
- `-T` (a flag of `docker compose exec`, not of psql): do not allocate a terminal.

**Variables.** psql has its own variables, set with `-v name=value` or `\set name value` or `\gset`. `:name` inserts the value into SQL; `:'name'` inserts it as a quoted text literal.

**Meta-commands.** Handled by psql, never sent to the server.

- `\gset`: after a query, put the result columns into variables named like the columns.
- `\if :variable`, `\elif`, `\else`, `\endif`: run a block only if the variable is true.
- `\o file` sends query output to a file (`\o /dev/null` discards it); `\o` alone restores the screen.
- `\d table`: describe a table (columns, indexes); `\di+`: list indexes with sizes; `\dt`: list tables; `\q` quit.

**Why meta-commands matter for scripts.** They only work in psql. Another program that reads the same `.sql` file (such as this repository's Python code) must skip those lines.

## Walkthrough of this repository's use

`Makefile`, lines 15 to 16:

```make
# How SQL files reach the server. CI overrides this with a plain `psql` on the runner.
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)
```

`docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)`:

- `docker compose exec -T db` runs a command in the `db` container, with no terminal (the input is a file).
- `psql` is the client. `-X` ignores personal settings. `-q` silences notices. `-v ON_ERROR_STOP=1` makes any SQL error stop the run and fail the `make` target.
- `-U $(PGUSER) -d $(PGDATABASE)` are the user and database (`lab` and `lab` by default). No `-h`: inside the container psql uses the local socket. The password is not needed there because the image trusts local connections.

`Makefile`, lines 37 to 44:

```make
# Every file is safe to run twice: IF NOT EXISTS in the schema, a seed that skips tables that have rows.
db: ## schema, 100,000 customers and 1,000,000 orders (about 30 seconds the first time), the lesson's queries
	$(PSQL) < sql/001_schema.sql
	$(PSQL) < sql/002_seed.sql
	$(PSQL) < sql/003_queries.sql

reset: ## drop the lab's tables (make db rebuilds them)
	$(PSQL) < sql/reset.sql
```

`$(PSQL) < sql/001_schema.sql` etc. feed the files. `make db` therefore stops at the first error.

### The meta-commands in the SQL

`sql/002_seed.sql`, lines 6 to 8:

```sql
SELECT NOT EXISTS (SELECT 1 FROM customers) AS customers_empty, NOT EXISTS (SELECT 1 FROM orders) AS orders_empty \gset

\if :customers_empty
```
`sql/003_queries.sql`, lines 1 to 4:

```sql
-- 003_queries.sql: the queries the lesson runs by hand. Plans for them are in explain/.
SET timezone = 'UTC';
\o /dev/null

```

`\gset` stores `customers_empty` and `orders_empty` (each the word `t` or `f`); `\if :customers_empty` and `\if :orders_empty` test them; `\endif` closes each block. In `003_queries.sql`, `\o /dev/null` hides the output of the wide queries until the bare `\o` (line 21) restores it. These lines are for psql only. In Python, `split_statements` drops every line whose first non-blank character is a backslash, so `PostgresLabIndexes` can run the migration and plan files that Python needs; the seed and the query file are only run by `make db`, never by Python.

### The interactive shell

`Makefile`, lines 87 to 88:

```make
psql: ## an interactive psql session
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)
```

`make psql` opens an interactive session: no `-T`, so Docker allocates a terminal; no `-X`/`-q`, so you get the normal friendly behaviour. Type `\d orders`, a query, `\q` to leave.

## Try it yourself

(After `make up db`.)

1. `make psql`, then type `\dt` and press Enter: lists `customers` and `orders`. `\d orders` shows the columns, the foreign key to `customers` and the indexes `orders_pkey` and `idx_orders_created_id`. `\q` quits.
2. `echo "select 1 as one;" | docker compose exec -T db psql -X -q -U lab -d lab` prints a one-row table.
3. `printf 'select 1/0;\nselect 2 as two;\n' | docker compose exec -T db psql -X -q -U lab -d lab; echo "exit=$?"` prints the error and still runs `select 2`; exit code 0. Now add `-v ON_ERROR_STOP=1` and it stops after the error with exit code 3.
4. `printf 'select 1 as flag \\gset\n\\echo :flag\n' | docker compose exec -T db psql -X -q -U lab -d lab` prints `1`.

## Mistakes people make

- Running a script without `ON_ERROR_STOP` and not noticing that half of it failed.
- Expecting `\gset` or `\if` to work in other clients.
- Forgetting the semicolon at the end of a statement typed interactively (psql waits for more input).
- Pasting a large script with a tab character, which triggers completion.
- Leaving a transaction open in an interactive session.

**How this repository avoids them.** `ON_ERROR_STOP=1` in the `PSQL` variable. `-X` for repeatability. Files with meta-commands are only run through psql; the Python runner strips them. The seed uses `\if` so repeating `make db` does not double the data.

## Check yourself

1. What does `-v ON_ERROR_STOP=1` change? *psql stops at the first error and exits with a non-zero code.*
2. What does `psql ... < file.sql` do? *Feeds the file to psql's standard input, so it runs the file's statements.*
3. What does `\gset` do? *Stores the columns of the last query's result in psql variables.*
4. Why does `-X` help repeatability? *It stops psql from reading the personal `~/.psqlrc` file.*
5. Where do meta-commands run? *In psql itself, never on the server.*

## Further reading

- PostgreSQL 18, `psql`: https://www.postgresql.org/docs/18/app-psql.html (options and "Meta-Commands").
