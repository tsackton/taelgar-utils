##!/bin/zsh

BUILD_PATH="../website/taelgarverse-build"
OBSIDIAN_PATH="/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar"

## run obsidan convert to build clean markdown
obsidianhtml convert -i config-build-md.yml

# convert markdown to html
obsidianhtml convert -i config-build-html.yml

# copy html to github repo
rsync -avz --exclude ".git" --exclude ".gitignore" --delete ../website/taelgarverse-build-html/ ../website/taelgarverse/

