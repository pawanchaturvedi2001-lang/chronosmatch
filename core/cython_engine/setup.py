
from setuptools import setup, Extension
from Cython.Build import cythonize

extensions = [
    Extension(
        name="matching_engine",
        sources=["matching_engine.pyx"],
    )
]

setup(
    name="chronosmatch-cython",
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
)


