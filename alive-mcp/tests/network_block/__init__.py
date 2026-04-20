"""Marker package so ``tests.network_block`` is importable.

The actual blocker is :mod:`sitecustomize` sibling — when this
directory is on ``PYTHONPATH``, Python auto-imports
``sitecustomize`` at interpreter startup, which registers the socket
block for the ENTIRE process (including any subprocess that inherits
the same ``PYTHONPATH``).

This file is intentionally empty aside from the docstring; adding
imports here would run BEFORE ``sitecustomize`` during Python's
site initialization and could break the ordering the block relies on.

See :mod:`sitecustomize` for the actual mechanism.
"""
