from busy_listing.infrastructure.sql_script import split_statements


def test_statements_are_split_on_semicolons():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_comments_are_dropped_even_with_a_semicolon_in_them():
    assert split_statements("-- one; two\nSELECT 1; -- trailing; note\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_a_semicolon_inside_quotes_does_not_split():
    assert split_statements("SELECT 'a;b'; SELECT \"c;d\";") == ["SELECT 'a;b'", 'SELECT "c;d"']


def test_psql_meta_commands_are_not_sql():
    assert split_statements("\\set rows 5\nSELECT 1;\n\\gset\n") == ["SELECT 1"]


def test_text_after_the_last_semicolon_is_ignored_like_an_empty_statement():
    assert split_statements("SELECT 1;\n  \n") == ["SELECT 1"]


def test_every_repository_sql_file_that_python_runs_splits_into_complete_statements():
    import pathlib

    sql = pathlib.Path(__file__).resolve().parents[3] / "sql"
    for path in [*sorted((sql / "migrations").rglob("*.sql")), *sorted((sql / "explain").glob("*.sql"))]:
        statements = split_statements(path.read_text())
        assert statements, path.name
        assert all(not statement.endswith(";") for statement in statements)
