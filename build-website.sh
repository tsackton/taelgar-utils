##!/bin/zsh

BUILD_PATH="../website/taelgarverse-build"
OBSIDIAN_PATH="/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar"

## clean build dirs
find $BUILD_PATH/* ! -path ".obsidian" -delete 
find ../website/taelgarverse-build-md/* ! -name "*.png" ! -name "*.jpg" ! -name "*.jpeg" -delete
find ../website/taelgarverse-build-html/* -delete 

## run taelgar_utils.py to generate fresh MD-only directory
python taelgar_utils.py --output $BUILD_PATH --dview --filter-text --campaign dufr .

## copy assets
rsync -avz -delete $OBSIDIAN_PATH/assets/ $BUILD_PATH/assets 

## run obsidan convert to build clean markdown
obsidianhtml convert -i config-build-md.yml

# convert markdown to html
obsidianhtml convert -i config-build-html.yml

# copy html to github repo
rsync -avz -delete -n ../website/taelgarverse-build-html/ ../website/taelgarverse/

## copy media, since it doesn't seem to build properly
# cp md/_media/* /Users/tim/Dropbox/Mac/Documents/Personal/RPGs/taelgarverse/_media

# move to git repo, push changes
# cd /Users/tim/Documents/RPGs/taelgarverse
# git add . --all
# git commit -a -m "autopublish website"
# git push