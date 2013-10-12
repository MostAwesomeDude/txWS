#!/usr/bin/env python

from setuptools import setup

setup(
    name="txWS",
    py_modules=["txws"],
    setup_requires=["vcversioner"],
    vcversioner={},
    author="Corbin Simpson",
    author_email="simpsoco@osuosl.org",
    description="Twisted WebSockets wrapper",
    long_description=open("README.rst").read(),
    license="MIT/X11",
    url="http://github.com/MostAwesomeDude/txWS",
)
