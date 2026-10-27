from busy_listing.domain.load import LoadTimings


def test_the_median_of_each_visited_page_is_reported_in_page_order():
    timings = LoadTimings(((100, 30.0), (0, 5.0), (100, 10.0), (100, 20.0), (0, 7.0)), 1.5)
    assert timings.median_by_page() == {0: 6.0, 100: 20.0}


def test_no_requests_means_no_medians():
    assert LoadTimings((), 0.0).median_by_page() == {}
