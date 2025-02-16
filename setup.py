import setuptools

setuptools.setup(
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
        "setuptools~=75.8.0",
        "PyYAML~=6.0.2",
        "coloredlogs~=15.0.1",
        "colour~=0.1.5",
        "iso639-lang~=2.5.1",
        "matplotlib~=3.10.0",
        "mpv~=1.0.7",
        "numpy~=2.2.3",
        "pyTelegramBotAPI~=4.26.0",
        "pydantic~=2.10.6",
        "python-mpv~=1.0.7",
        "readchar~=4.2.1",
        "rich~=13.9.4",
        "svgwrite~=1.4.3",
        "tqdm~=4.67.1",
        "urllib3~=2.3.0",
        "wiktionaryparser~=0.0.97",
    ],
)
