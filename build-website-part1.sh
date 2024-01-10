##!/bin/zsh

BUILD_PATH="../website/taelgarverse-build"
OBSIDIAN_PATH="/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar"

## clean build dirs
find "$BUILD_PATH"/* ! -path ".obsidian" -delete 
find ../website/taelgarverse-build-md/* ! -name "*.png" ! -name "*.jpg" ! -name "*.jpeg" -delete
find ../website/taelgarverse-build-html/* -delete 

## run taelgar_utils.py to generate fresh MD-only directory
python taelgar_utils.py --output $BUILD_PATH --filter-text --campaign dufr .

## copy assets
rsync -avz -delete "$OBSIDIAN_PATH/assets/" "$BUILD_PATH/assets"
cp -r "$OBSIDIAN_PATH/_scripts" $BUILD_PATH
cp -r "$OBSIDIAN_PATH/_templates" $BUILD_PATH
cp -r "$OBSIDIAN_PATH/.obsidian" $BUILD_PATH