# Small scaling utilities.
CFG_TIMEOUT = 30
CFG_RETRIES = 3


def scale(value, factor):
    result = value * factor
    return result
    # end scale


def total(items):
    running = 0
    for item in items:
        running += item
    return running
    # end total


print(scale(2, CFG_TIMEOUT), total([1, 2, 3]), CFG_RETRIES)
