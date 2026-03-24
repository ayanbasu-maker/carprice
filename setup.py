from setuptools import setup, find_packages

setup(
    name="carprice",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28",
        "beautifulsoup4>=4.11",
        "lxml>=4.9",
        "selenium>=4.10",
        "rich>=13.0",
        "pgeocode>=0.4",
        "click>=8.1",
    ],
    entry_points={
        "console_scripts": [
            "carprice=carprice.cli:main",
        ],
    },
)
