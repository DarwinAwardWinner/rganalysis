#!/bin/bash

cd $(dirname $0)

{
  # Before
  perl -lape 'do { print; exit; } if /<pre><code>/' README.mkdn
  # Help text
  ./rganalysis.py --help 2>&1
  # After
  perl -lane 'print if $found ||= m{</pre></code>}' README.mkdn
} > new_readme.txt

[ -s new_readme.txt ] && mv new_readme.txt README.mkdn
