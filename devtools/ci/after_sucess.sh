echo $TRAVIS_PULL_REQUEST $TRAVIS_BRANCH

if [[ "$TRAVIS_PULL_REQUEST" != "false" ]]; then
    echo "This is a pull request. No deployment will be done."; exit 0
fi

if [[ "$TRAVIS_BRANCH" != "master" ]]; then
    echo "No deployment on BRANCH='$TRAVIS_BRANCH'"; exit 0
fi

if [[ "2.7" =~ "$python" ]]; then
    conda install --yes binstar jinja2
        conda convert -p all ~/miniconda2/conda-bld/linux-64/ipynbtest-dev*.tar.bz2 -o ~/miniconda2/conda-bld/
    binstar -t ${BINSTAR_TOKEN}  upload  --force --u omnia -p ipynbtest-dev $HOME/miniconda2/conda-bld/*/ipynbtest-dev*.tar.bz2
fi

if [[ "$python" != "2.7" ]]; then
    echo "No deploy on PYTHON_VERSION=${python}"; exit 0
fi