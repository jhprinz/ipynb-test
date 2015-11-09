echo $TRAVIS_PULL_REQUEST $TRAVIS_BRANCH

#if [[ "$TRAVIS_PULL_REQUEST" != "false" ]]; then
#    echo "This is a pull request. No deployment will be done."; exit 0
#fi

#if [[ "$TRAVIS_BRANCH" != "master" ]]; then
#    echo "No deployment on BRANCH='$TRAVIS_BRANCH'"; exit 0
#fi

conda install --yes anaconda-client

if [[ "2.7" =~ "$python" ]]; then
    conda convert -p all ~/miniconda2/conda-bld/linux-64/ipynbtest*.tar.bz2 -o ~/miniconda2/conda-bld/
    anaconda -t ${BINSTAR_TOKEN} upload --force --user omnia --package ipynbtest $HOME/miniconda2/conda-bld/*/ipynbtest*.tar.bz2
fi

if [[ "$python" != "2.7" ]]; then
    echo "No deploy on PYTHON_VERSION=${python}"; exit 0
fi