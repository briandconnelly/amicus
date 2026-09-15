"""Shared conventions for agent bridges.

These modules standardize what every bridge says and checks — error taxonomy,
prompt framing, tool annotations, flag preflight, surface fingerprinting —
while leaving wire serialization to each consumer. A bridge's existing
envelope shape is its own closed contract; this layer supplies the shared
vocabulary and rules those shapes are built from.
"""
