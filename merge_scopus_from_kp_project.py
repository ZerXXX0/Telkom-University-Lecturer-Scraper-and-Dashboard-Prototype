import os
import json
from config import settings

def main():
    src_dir = '/home/zerx/KP_project/data/json'
    dest_dirs = [
        os.path.abspath('data/json'),
        os.path.abspath(settings.JSON_DIR)
    ]
    dest_dirs = list(set(dest_dirs))

    if not os.path.exists(src_dir):
        print(f"Source directory {src_dir} does not exist.")
        return

    src_files = [f for f in os.listdir(src_dir) if f.endswith('.json')]
    merged_count = 0

    for filename in src_files:
        src_path = os.path.join(src_dir, filename)
        try:
            with open(src_path, 'r', encoding='utf-8') as sf:
                src_data = json.load(sf)
        except Exception as e:
            print(f"Error reading source file {filename}: {e}")
            continue

        src_scopus = src_data.get("profiles", {}).get("scopus")
        if not src_scopus:
            continue

        # Try to find and update in all destination directories
        for dest_dir in dest_dirs:
            dest_path = os.path.join(dest_dir, filename)
            if os.path.exists(dest_path):
                try:
                    with open(dest_path, 'r', encoding='utf-8') as df:
                        dest_data = json.load(df)

                    # Update Scopus link only if it is missing or different
                    current_scopus = dest_data.get("profiles", {}).get("scopus")
                    if current_scopus != src_scopus:
                        dest_data["profiles"]["scopus"] = src_scopus
                        with open(dest_path, 'w', encoding='utf-8') as df:
                            json.dump(dest_data, df, indent=4)
                        print(f"Updated Scopus URL for {filename} -> {src_scopus}")
                        merged_count += 1
                except Exception as e:
                    print(f"Error updating dest file {dest_path}: {e}")

    print(f"\nSuccessfully merged/updated Scopus links in {merged_count} destinations.")

if __name__ == "__main__":
    main()
