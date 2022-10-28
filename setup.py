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
)
