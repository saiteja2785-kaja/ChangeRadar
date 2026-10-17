from demo_repo.api.products import get_product


def calculate_total(items):
    """items is a list of (product_id, quantity). Returns the total in rupees."""
    total = 0
    for product_id, qty in items:
        product = get_product(product_id)
        total += product["price"] * qty
    return total


def format_invoice_line(product_id, qty):
    product = get_product(product_id)
    amount = product["price"] * qty
    return f"{product['name']} x{qty}: Rs. {amount}"