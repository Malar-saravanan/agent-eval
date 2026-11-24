def add_item(item, cart=[]):
    cart.append(item)
    return cart


alice = add_item("apple")
bob = add_item("bread")
print(alice)  # expected: ['apple']
print(bob)    # expected: ['bread']
