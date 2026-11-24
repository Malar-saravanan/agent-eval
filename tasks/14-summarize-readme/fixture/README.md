# tinycache

tinycache is a small in-process caching library for Python. It stores the results of function calls in memory so
that expensive calls (database queries, HTTP requests) are not repeated.

## Install

    pip install tinycache

## Usage

    from tinycache import cached

    @cached(ttl=60)
    def get_user(user_id):
        ...

Entries expire after `ttl` seconds (default 300). The cache holds at most 1024 entries by default; when full, the
least recently used entry is evicted.

## Limitations

The cache lives inside one process: it is not shared between workers or machines. Versions before 0.4 are not
thread-safe.
