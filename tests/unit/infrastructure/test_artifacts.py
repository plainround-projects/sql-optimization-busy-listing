from busy_listing.infrastructure.artifacts import FileArtifactStore


def test_a_plan_is_written_next_to_its_name(tmp_path):
    store = FileArtifactStore(tmp_path / "out")
    store.save_plan("q1_day_before", ["Seq Scan on orders", "Execution Time: 1.0 ms"])
    assert (tmp_path / "out" / "q1_day_before.txt").read_text() == "Seq Scan on orders\nExecution Time: 1.0 ms\n"


def test_the_report_is_written_as_results_md(tmp_path):
    store = FileArtifactStore(tmp_path)
    store.save_report("# Results\n")
    assert (tmp_path / "results.md").read_text() == "# Results\n"
