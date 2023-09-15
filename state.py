import json

_CACHE = {}

def save(fname):
    with open(fname, 'w') as f:
        f.write(json.dumps(_CACHE))

def load(fname):
    global _CACHE
    with open(fname, 'r') as f:
        _CACHE = {**_CACHE, **json.load(f)}
        return _CACHE

def clear():
    global _CACHE
    _CACHE = {}

def has(k):
    return str(k) in _CACHE

def put(k, v):
    _CACHE[str(k)] = v
    return v

def get(k, default=None):
    return _CACHE.get(str(k), default)
