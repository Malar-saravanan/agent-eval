# Small scaling utilities.
TIMEOUT = 30
retries = 3


def scale(v, f):
    r = v * f
    return r


def total(items):
    t = 0
    for i in items:
        t += i
    return t


print(scale(2, TIMEOUT), total([1, 2, 3]), retries)
