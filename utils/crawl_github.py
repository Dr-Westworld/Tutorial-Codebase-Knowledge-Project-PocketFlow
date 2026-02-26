
from gh_crawler import gh_crawler
import os 

import github_crawler

github_token = os.environ.get("GITHUB_TOKEN")
# print(f"Token found: {github_token is not None}")  # ← Add this debug line
# print(f"Token value: {github_token[:5]}..." if github_token else "None")  # ← Check first 10 chars

if not github_token:
    print("Warning: No GitHub token found in environment variable 'GITHUB_TOKEN'.\n"
            "Private repositories will not be accessible without a token.\n"
            "To access private repos, set the environment variable or pass the token explicitly.")

repo_url = "https://github.com/010624/Data-Warehouse-and-Mining/tree/main"

# Example: Get Python and Markdown files, but exclude test files
files, stats = github_crawler.crawl_github_files_py(
    repo_url, 
    token=github_token,
    max_file_size=1 * 1024 * 1024,  # 1 MB in bytes
    use_relative_paths=True,  # Enable relative paths
    include_patterns=["*.py", "*.md"],  # Include Python and Markdown files
)

# files = result["files"]
# stats = result["stats"]

# print(f"\nDownloaded {stats['downloaded_count']} files.")
# print(f"Skipped {stats['skipped_count']} files due to size limits or patterns.")
# print(f"Base path for relative paths: {stats['base_path']}")
# print(f"Include patterns: {stats['include_patterns']}")
# print(f"Exclude patterns: {stats['exclude_patterns']}")

# # Display all file paths in the dictionary
# print("\nFiles in dictionary:")
# for file_path in sorted(files.keys()):
#     print(f"  {file_path}")

# # Example: accessing content of a specific file
# if files:
#     sample_file = next(iter(files))
#     print(f"\nSample file: {sample_file}")
#     print(f"Content preview: {files[sample_file][:200]}...")

print(f"\nDownloaded {stats['downloaded_count']} files.")
print(f"Skipped {stats['skipped_count']} files due to size limits or patterns.")
print(f"Base path for relative paths: {stats['base_path']}")
print(f"Include patterns: {stats['include_patterns']}")
print(f"Exclude patterns: {stats['exclude_patterns']}")

print("\nFiles in dictionary:")
for file_path in sorted(files.keys()):
    print(f"  {file_path}")

if files:
    sample_file = next(iter(files))
    print(f"\nSample file: {sample_file}")
    print(f"Content preview: {files[sample_file][:200]}...")