#!/bin/sh
# This script was taken from https://github.com/pandegroup/mdtraj/tree/master/devtools

### Install Miniconda

echo travis_fold:start:install.conda
echo Install conda

MINICONDA=Miniconda2-latest-Linux-x86_64.sh

if [[ "$CONDA_PY" == "27" ]]; then
    MINICONDA=Miniconda2-4.2.12-Linux-x86_64.sh
else
    MINICONDA=Miniconda3-4.2.12-Linux-x86_64.sh
fi

MINICONDA_MD5=$(curl -s https://repo.continuum.io/miniconda/ | grep -A3 $MINICONDA | sed -n '4p' | sed -n 's/ *<td>\(.*\)<\/td> */\1/p')
wget https://repo.continuum.io/miniconda/$MINICONDA
if [[ $MINICONDA_MD5 != $(md5sum $MINICONDA | cut -d ' ' -f 1) ]]; then
    echo "Miniconda MD5 mismatch"
    echo "Expected: $MINICONDA_MD5"
    echo "Found: $(md5sum $MINICONDA | cut -d ' ' -f 1)"
    exit 1
fi

bash $MINICONDA -b -p $HOME/miniconda

export PATH=$HOME/miniconda/bin:$PATH
hash -r

# add omnia and update
conda config --add channels http://conda.anaconda.org/omnia
conda update --yes conda

conda info -a

echo travis_fold:end:install.conda

  # Replace dep1 dep2 ... with your dependencies
  - conda create -q -n test-environment python=$TRAVIS_PYTHON_VERSION dep1 dep2 ...
  - source activate test-environment
  - python setup.py install