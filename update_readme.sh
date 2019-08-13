#!/bin/bash

cd $(dirname $0)

export PYTHONPATH="./rganalysis:$PYTHONPATH"
SCRIPT=./scripts/rganalysis
$SCRIPT --help &>/dev/null || {
    echo "Cannot run rganalysis.py:"
    # Run it again to print the error message
    $SCRIPT --help
    exit 1
}

# This inserts the new help text into the README file
{
  # Before
  perl -lape 'do { print; exit; } if /<pre><code>/' README.mkdn
  # Help text
  $SCRIPT --help 2>&1
  # After
  perl -lane 'print if $found ||= m{</pre></code>}' README.mkdn
} > new_readme.txt

[ -s new_readme.txt ] && mv new_readme.txt README.mkdn
