#!/usr/bin/env python

"""The setup script."""

from setuptools import find_packages, setup

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements = [
    "Click>=7.0",
]

test_requirements = [
    "pytest>=3",
]

setup(
    author="Hossein Ghorbanfekr",
    author_email="hgh.comphys@gmail.com",
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    description="A machine-learning framework for development of interatomic potential",
    entry_points={
        "console_scripts": [
            "mlpot=mlpot.cli:main",
        ],
    },
    install_requires=requirements,
    license="GNU General Public License v3",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="mlpot",
    name="mlpot",
    packages=find_packages(include=["mlpot", "mlpot.*"]),
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/hghcomphys/mlpot",
    version="0.4.0",
    zip_safe=False,
)
