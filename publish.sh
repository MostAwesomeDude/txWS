#!/usr/bin/env bash

set -o nounset
set -o errexit

#------------------------------------------------------------------------------
# Configure package preferences here
PY_PACKAGE="txwebsocket"


#------------------------------------------------------------------------------
PIP_PACKAGE=${PY_PACKAGE//_/-} # Replace _ with -
HAS_GIT=`ls -d .git 2> /dev/null`


if ! [ -f "setup.py" ]; then
    echo "setver.sh must be run in the directory where setup.py is" >&2
    exit 1
fi

VER="${1:?You must pass a version of the format 0.0.0 as the only argument}"

if [ $HAS_GIT ]; then
    if [ -n "$(git status --porcelain)" ]; then
        echo "There are uncomitted changes, please make sure all changes are comitted" >&2
        exit 1
    fi

    if git tag | grep -q "${VER}"; then
        echo "Git tag for version ${VER} already exists." >&2
        exit 1
    fi
fi

#------------------------------------------------------------------------------
echo "Setting version to $VER"

# Update the setup.py
sed -i "s;^package_version.*=.*;package_version = '${VER}';"  setup.py

# Update the package version
sed -i "s;.*version.*;__version__ = '${VER}';" txws.py

# Reset the commit, we don't want versions in the commit

if [ $HAS_GIT ]; then
    git commit -a -m "Updated to version ${VER}"

    git tag ${VER}
    git push
    git push --tags
fi

#------------------------------------------------------------------------------

echo "Deleting old dist dir"
[ ! -d dist ] || rm -rf dist

echo "Building sdist"
python setup.py sdist

echo "Pushing to pypi index server "
twine upload dist/*
