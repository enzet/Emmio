from setuptools import setup

setup(
    name="Emmio",
    version="0.1",
    packages=["emmio"],
    url="https://github.com/enzet/Emmio",
    license="",
    author="Sergey Vartanov",
    author_email="me@enzet.ru",
    description="Language learning toolbox",
    entry_points={
        "console_scripts": ["emmio=emmio.__main__:main"],
    },
    install_requires=[
        "PyYAML~=6.0",
        "coloredlogs",
        "colour~=0.1.5",
        "iso-639",
        "matplotlib~=3.5.2",
        "mpv~=0.1",
        "numpy~=1.22.3",
        "pyTelegramBotAPI",
        "pydantic~=1.10.2",
        "python-mpv",
        "rich~=12.3.0",
        "setuptools~=65.5.1",
        "svgwrite~=1.4.2",
        "tqdm",
        "urllib3~=1.26.9",
        "wiktionaryparser~=0.0.97",
    ],
)
