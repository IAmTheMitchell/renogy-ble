from setuptools import setup, find_packages

setup(
    name="renogy-ble",
    version="0.1.0",
    author="Mitchell Carlson",
    author_email="mitchell.carlson.pro@gmail.com",
    description="A library for parsing Renogy BLE data",
    url="https://github.com/IAmTheMitchell/renogy-ble",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)