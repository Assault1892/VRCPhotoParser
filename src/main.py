import argparse
import json
import sys

from PIL import Image
from PIL.PngImagePlugin import PngInfo


def parse_png_metadata(file_path):
    try:
        with Image.open(file_path) as img:
            if img.format != "PNG":
                print(
                    f"Error: File '{file_path}' is not a PNG image (Format: {img.format})"
                )
                return

            print(f"--- Basic Information ---")
            print(f"Filename: {file_path}")
            print(f"Size: {img.width}x{img.height}")
            print(f"Mode: {img.mode}")

            # Extract metadata from img.info
            metadata = img.info

            if not metadata:
                print("\nNo additional metadata (text chunks) found.")
                return

            print(f"\n--- PNG Metadata (Targeted Chunks) ---")
            found_target = False
            for key, value in metadata.items():
                # Handle bytes values (PNG chunks can be utf-8 or latin-1)
                if isinstance(value, bytes):
                    try:
                        raw_str = value.decode('utf-8').strip()
                    except:
                        raw_str = value.decode('latin-1', errors='ignore').strip()
                elif isinstance(value, str):
                    raw_str = value.strip()
                else:
                    continue
                
                should_display = False
                display_value = raw_str

                # Target 1: [XML:com.adobe.xmp] (Key based)
                if key == "XML:com.adobe.xmp":
                    should_display = True
                
                # Target 2: VRCX/VRChat (Key is "Description" or Value contains "[Description]")
                elif key == "Description" or "[Description]" in raw_str:
                    should_display = True
                    # Look for JSON part starting with '{'
                    json_start = raw_str.find('{')
                    if json_start != -1:
                        json_data = raw_str[json_start:].strip()
                        try:
                            parsed_json = json.loads(json_data)
                            display_value = json.dumps(parsed_json, indent=4, ensure_ascii=False)
                        except json.JSONDecodeError:
                            # If parsing fails, fall back to stripped string
                            if "[Description]" in raw_str:
                                display_value = raw_str.replace("[Description]", "").strip()
                    elif "[Description]" in raw_str:
                        display_value = raw_str.replace("[Description]", "").strip()

                if should_display:
                    print(f"[{key}]:")
                    print(display_value)
                    print("-" * 20)
                    found_target = True

            if not found_target:
                print("No XMP or VRCX metadata found in this image.")

    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
    except Exception as e:
        print(f"Error: An unexpected error occurred: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract and display specific PNG metadata (XMP and VRCX/Description)."
    )
    parser.add_argument("file", help="Path to the PNG image file")

    args = parser.parse_args()
    parse_png_metadata(args.file)


if __name__ == "__main__":
    main()
