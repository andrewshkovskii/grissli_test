import re

from setuptools import find_packages, setup

install_requires = [
    'aiohttp==0.22.5',
    'beautifulsoup4==4.5.1',
    'python-dateutil==2.5.3'
]

with open('grissli_test/__init__.py', 'r') as fd:
    version = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
                        fd.read(), re.MULTILINE).group(1)

setup(
    name='grissli_test',
    version=version,
    description='',
    long_description=__doc__,
    url='http://',
    license='EULA',
    author='Andrey Baryshnikov <andrewshkovskii@gmail.com>',
    author_email="andrewshkovskii@gmail.com",
    packages=find_packages(exclude=('',)),
    entry_points={
        'console_scripts': [
            'grissli_test = grissli_test.runserver:main',
        ]
    },
    zip_safe=False,
    install_requires=install_requires,
    include_package_data=True,
    classifiers=['Private :: Do Not Upload'],
)
