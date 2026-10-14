"""
ChronosMatch Setup Script
Builds the Cython-accelerated Limit Order Book native extension.

Usage:
    python setup.py build_ext --inplace
"""

import sys
import os
from setuptools import setup, Extension

try:
    from Cython.Build import cythonize
    HAVE_CYTHON = True
except ImportError:
    HAVE_CYTHON = False

ext_modules = []

if HAVE_CYTHON:
    # Compiler optimization flags
    if sys.platform == "win32":
        extra_compile_args = ["/O2", "/fp:fast"]
        extra_link_args = []
    else:
        extra_compile_args = ["-O3", "-march=native", "-ffast-math"]
        extra_link_args = []

    ext_modules = cythonize(
        [
            Extension(
                "core.cython_engine.order_book",
                sources=["core/cython_engine/order_book.pyx"],
                extra_compile_args=extra_compile_args,
                extra_link_args=extra_link_args,
                language="c",
            )
        ],
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
            "initializedcheck": False,
        },
    )

setup(
    name="chronosmatch",
    version="0.2.0",
    description="ChronosMatch Zero-Copy High-Frequency Trading Engine",
    ext_modules=ext_modules,
)

