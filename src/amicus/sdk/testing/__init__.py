"""Importable test kit for bridges built on pontonier.

Framework-agnostic by design: every check returns a list of violation strings
(empty = pass) instead of asserting, so a consumer wires it into pytest with a
one-line ``assert not violations``, or into any other harness. Nothing here
imports pytest.
"""
