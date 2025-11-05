#!/bin/sh

OBSIDIAN_PATH="/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar/"
cd export
cp ~/Google\ Drive/My\ Drive/RPGs/Taelgar/Dunmari\ Campaign/Party_Treasure.docx Party_Treasure_import.docx
cp ../../website/taelgarverse-build-md/Campaigns/Dunmari\ Frontier/Party\ Treasure.md treasure.md
python "$OBSIDIAN_PATH"/.scripts/filter-secrets.py save treasure.md . < treasure.md > Party_Treasure_export.md
perl -p -i.bak -e 's/%%SECRET\[\d+\]%%//g' Party_Treasure_export.md   
perl -p -i.bak2 -e 's/\.\.\/\.\.\//https:\/\/tsackton\.github\.io\/taelgarverse\//g' Party_Treasure_export.md 
perl -p -i.bak3 -e 's/\.md\)/\.html\)/g'  Party_Treasure_export.md
pandoc -f gfm -t docx --toc -o Party_Treasure.docx --shift-heading-level-by=-1 Party_Treasure_export.md
cp Party_Treasure.docx ~/Google\ Drive/My\ Drive/RPGs/Taelgar/Dunmari\ Campaign/