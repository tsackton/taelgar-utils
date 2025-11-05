import os
import pathspec
import argparse

def parse_arguments():
    """ Parse command line arguments """
    parser = argparse.ArgumentParser(description='Delete files based on .gitignore rules')
    parser.add_argument('gitignore', help='Path to the cleanup file, in gitignore syntax')
    parser.add_argument('root_directory', help='Root directory path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Perform a dry run without deleting files')
    return parser.parse_args()

def parse_gitignore(file_path):
    """ Parse the .gitignore file with pathspec """
    with open(file_path, 'r') as file:
        spec = pathspec.PathSpec.from_lines('gitwildmatch', file)
    return spec

def delete_ignored_files(root_dir, gitignore_spec, verbose, dry_run):
    """ Delete files in the root directory that match .gitignore patterns, or just list them if dry-run """
    for root, dirs, files in os.walk(root_dir, topdown=True):
        # Skip .obsidian directories
        dirs[:] = [d for d in dirs if d != '.obsidian']

        for name in files:
            file_path = os.path.relpath(os.path.join(root, name), root_dir)
            if gitignore_spec.match_file(file_path):
                full_path = os.path.join(root, name)
                if dry_run:
                    print(f"Would delete: {full_path}")
                if verbose:
                    print(f"Deleting: {full_path}")
                if not dry_run:
                    os.remove(full_path)

def main():
    args = parse_arguments()
    gitignore_spec = parse_gitignore(args.gitignore)
    delete_ignored_files(args.root_directory, gitignore_spec, args.verbose, args.dry_run)

if __name__ == "__main__":
    main()
