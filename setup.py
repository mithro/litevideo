#!/usr/bin/env python3

import sys
from setuptools import setup
from setuptools import find_packages

import versioneer


if sys.version_info[:3] < (3, 3):
    raise SystemExit("You need Python 3.3+")


setup(
    name="litevideo",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    description="Small footprint and configurable video cores",
    long_description=open("README").read(),
    author="Florent Kermarrec",
    author_email="florent@enjoy-digital.fr",
    url="http://enjoy-digital.fr",
    download_url="https://github.com/enjoy-digital/litevideo",
    license="BSD",
    platforms=["Any"],
    keywords="HDL ASIC FPGA hardware design",
    classifiers=[
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",  # noqa
        "Environment :: Console",
        "Development Status :: Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
    ],
    packages=find_packages(),
    setup_requires=['setuptools-pep8'],
    install_requires=["litex"],
    test_requires=["Pillow"],
    include_package_data=True,
)
