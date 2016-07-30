from setuptools import setup, find_packages
setup(
    name='rganalysis',
    version='3.1',
    description='A script to add ReplayGain tags to your music library',
    url='https://github.com/DarwinAwardWinner/rganalysis',
    author='Ryan C. Thompson',
    author_email='rct+rganalysis@thompsonclan.org',
    license='GPLv2+',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: End Users/Desktop',
        'Environment :: Console',
        'Topic :: Multimedia :: Sound/Audio :: Analysis',
        'License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3 :: Only',
    ],
    keywords='audio replaygain',
    packages=find_packages(exclude=['scripts']),
    install_requires=[
        'audiotools',
        'mutagen',
        'plac',
    ],
    extras_require = {
        'progress_bars':  ["tqdm"],
    },
    scripts=['scripts/rganalysis',],
)
