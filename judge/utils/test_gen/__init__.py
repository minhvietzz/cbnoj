"""Declarative test-input generator for the MCP tools.

The caller (an AI assistant) never sends generator code: it sends a JSON `spec` that picks block types
and parameters, and this package turns it into input files with its own, trusted code.
"""
from judge.utils.test_gen.expr import Expr, SpecError  # noqa: F401
from judge.utils.test_gen.generator import (HELP_TEXT, Limits, generate_all, generate_preview,  # noqa: F401
                                            validate_spec)
