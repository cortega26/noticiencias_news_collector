from news_collector.utils.refinery_helper import has_no_activity


def test_none_is_no_activity():
    assert has_no_activity(None) is True


def test_empty_list_is_no_activity():
    assert has_no_activity([]) is True


def test_nonempty_list_is_activity():
    assert has_no_activity(["event"]) is False


def test_non_list_truthy_is_activity():
    assert has_no_activity("something") is False


def test_non_list_falsy_is_no_activity():
    assert has_no_activity("") is True
