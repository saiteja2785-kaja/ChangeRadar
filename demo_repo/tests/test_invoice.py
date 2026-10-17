from demo_repo.invoice_service.invoice import calculate_total


def test_empty_cart_total_is_zero():
    assert calculate_total([]) == 0