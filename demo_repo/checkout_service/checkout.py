from demo_repo.api.products import get_product
from demo_repo.invoice_service.invoice import calculate_total

FREE_SHIPPING_THRESHOLD = 500  # rupees


def checkout_summary(items):
    lines = []
    for product_id, qty in items:
        product = get_product(product_id)
        lines.append({"name": product["name"], "price": product["price"], "qty": qty})
    return lines


def shipping_fee(items):
    total = calculate_total(items)
    return 0 if total >= FREE_SHIPPING_THRESHOLD else 40