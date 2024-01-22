#!/bin/zsh

## autobuild Taelgarverse website

## set variables
## path of the source vault, relative to the root of the website repo
SOURCE_PATH="taelgar"
## path to the autobuild python script, relative to the root of the website repo
RUN_SCRIPT="taelgar-utils/website/build_mkdocs_site.py.py"
## assumes this script is in the root of the website repo
BUILD_PATH=$(pwd)

# convert relative paths to absolute paths
SOURCE_PATH="$BUILD_PATH/$SOURCE_PATH"
RUN_SCRIPT="$BUILD_PATH/$RUN_SCRIPT"

## check if needed files are present: autobuild.json, website.json
if [ ! -f autobuild.json ]; then
    echo "autobuild.json not found"
    exit 1
fi

if [ ! -f website.json ]; then
    echo "website.json not found"
    exit 1
fi

## clean source
cd $SOURCE_PATH
git reset --hard
# update submodules
cd $BUILD_PATH
git submodule update --remote --rebase
# run autobuild
python $RUN_SCRIPT

# optionally run mkdocs serve or deploy
if [ "$1" = "serve" ]; then
    mkdocs serve
elif [ "$1" = "deploy" ]; then
    git add --all
    git commit -m "autobuild"
    git push
fi
