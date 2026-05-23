from news_collector.utils.dict_wrapper import SafeNamespace


def test_init_sets_attributes():
    ns = SafeNamespace(foo="bar", count=42)
    assert ns.foo == "bar"
    assert ns.count == 42


def test_missing_attr_returns_none():
    ns = SafeNamespace(x=1)
    assert ns.y is None


def test_empty_namespace_returns_none():
    ns = SafeNamespace()
    assert ns.anything is None


def test_overwrite_attr():
    ns = SafeNamespace(val=1)
    ns.val = 99
    assert ns.val == 99
