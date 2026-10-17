from demo_repo.checkout_service.checkout import shipping_fee


def test_empty_cart_pays_shipping():
    assert shipping_fee([]) == 40