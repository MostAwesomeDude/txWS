#!/usr/bin/env python

from setuptools import setup

setup(
    name="txWS",
    version="0.5",
    py_modules = ["txws"],
    install_requires=[
        "Twisted",
    ],
    author="Corbin Simpson",
    author_email="simpsoco@osuosl.org",
    description="Twisted WebSockets wrapper",
    license="MIT/X11",
    url="http://github.com/MostAwesomeDude/txWS",
)
