# How to Build the Taelgarverse Website

Taelgarverse is a website that is auto-generated from markdown files stored in an Obsidian vault. There are a number of steps that are required to convert dynamic Obsidian markdown notes into static markdown notes compatible with material for mkdocs, which is the static site generator used to create taelgarverse.

This directory contains files needed to build a copy of the Taelgarverse website, based on the Material for Mkdocs theme.

This process can be automated using the autobuild_website.sh script and the build_mkdocs_site.py Python program. 

## Basic Workflow

We use a Obsidian-based Javascript code to prep a source directory for conversion, primarily to generate static, mkdocs-compliant versions of dynamic headers. We then use a Python script to auto-generate mkdocs-compliant markdown from the now-static source directory into the mkdocs `docs/` directory. 

Assuming the `source` directory is submodule, the basic build protocol is:
1. `git pull` from the source directory to get any updates to source material
2. open the `source` directory as an Obsidian vault, and run the `prep_for_export` template to make dynamic pages static
3. run `python path/to/this/repo export_vault.py` to build the website, *from the website base directory that contains your mkdocs.yml*
4. run `mkdocs serve` for local testing, or push upstream to build the live site.

The `export_vault.py` script handles the following operations, most of which can be configured in the **website.json** file.
- process an optionally filtered set of markdown files in the source directory, including convert wikilinks, slugify file and directory names, remove comments, set metadata, and process supported code blocks; these files are then exported to the docs directory
- process image files to compress/downsize and delete unused files to make the website repo smaller
- build a nav file for the literate nav mkdocs plugin
- copy required CSS and html overrides to a specified overrides directory

Required CSS/html are currently:
- `overrides/assets/stylesheets/leaflet.css`, for managing leaflet maps
- `overrides/assets/stylesheets/taelgarverse.css`, for basic site functionality
- `overrides/partials/toc.html`, for inserting backlinks

Site extras include:
- `assets/images/banner-map.png`, the default home page banner map
- `assets/images/logo.png`, the default logo, partially transparent
- `assets/images/logo-*.png`, alternate logo versions or styles
- `assets/stylesheets/homepage.css`, the homepage CSS to set up a [homepage like this](https://tsackton.github.io/taelgarverse/)
- `assets/stylesheets/homepage-informatics.css`, the homepage CSS to set up a [homepage like this](https://informatics.fas.harvard.edu/)
- `assets/stylesheets/styling.css`, sets color scheme for elements, including in taelgarverse.css; website will probably look bad without a version of this
- `home.html`, the html template that works with the [Taelgarverse homepage](https://tsackton.github.io/taelgarverse/); set the template metadata yaml in your `home_source` file to point to this
- `home-informatics.html`, the html template the works with the [Informatics homepage](https://informatics.fas.harvard.edu/)

The `build_mkdocs_site.py` Python program handles the following operations, configured in the **autobuild.json** file.
- open Obsidian and run the `prep_for_export` template to static-ify pages
- when that finishes (when you quit Obsidian), run the `export_vault.py` script to set up the mkdocs set

The `autobuild_website.sh` script handles git operations, and runs the `build_mkdocs_site.py` command. It must be run from the root of the website repo; the autobuild.json and website.json files must also be in that directory. This version can be run as: `autobuild_website.sh deploy` to push to remote, or `autobuild_website.sh serve` to serve locally using `mkdocs serve`. 

## Configuration Files

Both the `export_vault.py` and the `build_mkdocs_site.py` scripts have a number of configuration options that are specified in json files, which must be placed in the root dir of the website directory. Example configs are below.

### website.json

#### Paths 
- `source`, the source directory containing input files to be converted. Defaults to None. Required.
- `build`, the directory to put output in. Defaults to docs.
- `overrides_source`, the path to shared overrides that will be copied to `overrides_dest`. Defaults to `taelgar-utils/website/overrides`
- `overrides_dest`, the path where shared overrides will be copied. Defaults to `overrides`. Must be set as custom dir in mkdocs config.
- `slugify`, logical, if true, will slugify file names and folder names when exporting to `build`. Defaults to True.
- `clean_build`, logical, if true, will delete all files in `build` directory before starting processing. Defaults to False.

#### Templates
- `clean_code_blocks`, logical, if true will attempt to clean up code blocks using templates
- `codeblock_template_dir`, the directory where html templates to replace codeblocks are stored (currently only leaflet is implemented; mermaid is passed unaltered, everythign else is removed). Defaults to `taelgar-utils/website/templates`
- `home_source`, the template for the home page. No default, will not create if missing.
- `home_dest`, the file to be created for the home page, in `"build"`, usually `index.md`
- `literate_nav_source`, a template to generate the literate nav from. No default, will not create if missing.
- `literate_nav_dest`, the file to generate for the literate nav, must match mkdocs.yml

#### File Cleanup and Processing
- `campaign`, a campaign key; if set, then text in between %%^Campaign:key%% %%^End%% blocks will be removed if key does not match the value in "campaign". Can be a comma-separated list or an explicit (`[campaign1, campaign2]`) list.
- `export_date`, a date (in YYYY, YYYY-MM, or YYYY-MM-DD format); if set, then text in bewteen %%^Date:date%% %%^End%% blocks will be removed if export_date < date.
- `fix_links`, logical; if true, will convert `[[wikilinks]]` to `[standard markdown](path/to/standard-markdown.md)` links. Defaults to True.
- `strip_comments`, logical; if true, will remove text between %% %% blocks. Defaults to True.
- `clean_inline_tags`, logical, if true, will replace (tag:: value) with tag value. Special processing for (DR::) inline tags to produce nice-looking dates. Defaults to True.

#### File Metadata Assignment
- `hide_toc_tags`, a list of tags to add the hide: [toc] metadata to for mkdocs
- `hide_nav_tags`, a list of tags to add the hide: [nav] metadata to for mkdocs
- `hide_backlins_tags`, a list of tags to add hide_backlinks: True to metadata, used by the toc.html partial to hide backlinks in the sidebar.

#### File Selection
Note that skip/exclude operations happen prior to link generation, so links that point to skipped/excluded files will be removed
- `unnamed_files`, if present and "skip", unnamed files (~ in file name or title) are skipped and not copied to docs; if present and "unlist", unnamed files are copied but skipped from the nav generation globs
- `stub_files`, set to either skip or unlist, with the same behavior as `unnamed_files` but for files that consist of nothing but blank lines, h1, and the word stub/(stub)
- `skip_future_dated`, logical, if true then pages with activeYear > export_date will be excluded from processing and not copied to build dir
- `ignore_file`, a gitignore-style file that specifies files/glob patterns; any file matching these patterns will be excluded from processing and not copied to build dir

#### Misc Other
- `abs_path_root`, a string, e.g., "/", or "/taelgarverse/" prepended to various image paths when needed to construct absolute paths instead of relative paths (currently used for leaflet and backlinks)
- `resize_images`, logical, if true images are resized to max_height / max_width (longest dimension is used and aspect ratio is fixed)
- `max_height`, max image height in pixels for resize operations, defaults to 1600. Specify as integer.
- `max_width`, max image width in pixels for resize operations, defaults to 1600. Specify as integer.
- `delete_unlinked_images`, logical, if True, attempts to delete images that are not linked to any pages in docs. Requires `image_path`
- `image_path`, path, relative to `build`, to check for image files and compare against linked files.

### autobuild.json

The following config options need to be set in autobuild.json:

- `obs_json_path`, pointing to the path of the templater config that sets the prep_for_export template to run on load. Defaults to `taelgar-utils/website/obsidian-template-config.json`.
- `obsidian_vault_id`, the vault ID of the obsidian vault to static-ify. Defaults to None, so must be set manually.
- `obsidian_vault_root`, the path, relative to the website root, of the obsidian vault to static-ify. Defaults to `taelgar`.
- `export_script`, the path to the export script to run to autogenerate the mkdocs site. Defaults to `taelgar-utils/export_vault.py`.
