from coldchain.prep import plan_window

DAY = 1_800_000_000 // 3600 * 3600  # an hour boundary


def test_window_is_a_full_day_when_the_index_is_old():
    assert plan_window(DAY + 7200, DAY - 40 * 3600, 24) == (DAY + 7200 - 24 * 3600, DAY + 7200)


def test_window_starts_after_the_newest_indexed_minute():
    last = DAY + 46 * 60
    assert plan_window(DAY + 5 * 3600, last, 24) == (last + 60, DAY + 5 * 3600)


def test_window_avoids_the_key_of_the_last_baseline_file():
    last = DAY + 5 * 60  # baseline ends 5 minutes into its hour: its hourly file key is DAY
    begin, _ = plan_window(DAY + 3 * 3600, last, 24)
    assert begin == DAY + 600


def test_no_window_when_the_index_reaches_now():
    assert plan_window(DAY + 3600, DAY + 3600 - 60, 24) is None


def test_no_history_gives_the_full_window():
    assert plan_window(DAY + 24 * 3600, None, 24) == (DAY, DAY + 24 * 3600)
