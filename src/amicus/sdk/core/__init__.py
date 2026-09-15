"""The sdk's leaf layer.

These modules carry no backend-specific knowledge. The dependency rule is one-way:
``amicus.sdk.core`` never imports from the rest of the ``amicus.sdk`` package (enforced by
import-linter in CI), so a backend can use the runtime, redaction or path-alias sanitizing
without taking on the protocol or the conventions.
"""
