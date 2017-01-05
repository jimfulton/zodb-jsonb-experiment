name, version = 'j1m.relstoragejsonsearch', '0.1.0'

install_requires = [ 'relstorage[postgresql]',
                     'setuptools', 'psycopg2', 'ZODB']
extras_require = dict(test=['manuel', 'mock', 'zope.testing'])

entry_points = """
[console_scripts]
rs-json-updater = j1m.relstoragejsonsearch.updater:main
"""

from setuptools import setup

setup(
    author = 'Jim Fulton',
    author_email = 'jim@jimfulton.info',

    name = name, version = version,
    packages = [name.split('.')[0], name],
    namespace_packages = [name.split('.')[0]],
    package_dir = {'': 'src'},
    install_requires = install_requires,
    zip_safe = False,
    entry_points=entry_points,
    package_data = {name: ['*.txt', '*.test', '*.html']},
    extras_require = extras_require,
    tests_require = extras_require['test'],
    test_suite = name+'.tests.test_suite',
    )
