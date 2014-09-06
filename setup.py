from setuptools import setup, find_packages
from river import __version__

setup(
    name = 'river',
    version = __version__,
    packages = find_packages(),
    author = 'Eric Davis',
    author_email = 'eric@davising.com',
    url = 'https://github.com/edavis/river',
    entry_points = {
        'console_scripts': [
            'river = river.main:main',
        ],
    },
    install_requires = [
        'PyYAML==3.11',
        'arrow==0.4.4',
        'feedparser==5.1.3',
        'requests==2.3.0',
        'bleach==1.4',
        'jinja2==2.7.3',
    ],
    package_data = {
        'river': [
            'templates/*',
        ],
    },
)
