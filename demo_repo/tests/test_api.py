from demo_repo.api.products import get_product


def test_get_product_returns_price():
    assert get_product("book")["price"] == 500