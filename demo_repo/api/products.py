PRODUCTS = {
        "book": {"name": "Book", "price": 50000},
    "pen": {"name": "Pen", "price": 5000},
}


def get_product(product_id):
    product = PRODUCTS[product_id]
    return {"id": product_id, "name": product["name"], "price": product["price"]}