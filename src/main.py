import argparse
import json
import sys
import xml.dom.minidom

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
                        raw_str = value.decode("utf-8").strip()
                    except:
                        raw_str = value.decode("latin-1", errors="ignore").strip()
                elif isinstance(value, str):
                    raw_str = value.strip()
                else:
                    continue

                should_display = False
                display_value = raw_str

                # Target 1: VRChat ([XML:com.adobe.xmp] (Key based))
                if key == "XML:com.adobe.xmp":
                    should_display = True
                    try:
                        dom = xml.dom.minidom.parseString(raw_str)
                        # Pretty print the XML
                        pretty_xml = dom.toprettyxml(indent="    ")
                        # Filter out empty lines often added by toprettyxml
                        display_value = "\n".join(
                            [line for line in pretty_xml.splitlines() if line.strip()]
                        )
                    except Exception:
                        # Fallback to raw string if XML parsing fails
                        pass

                # Target 2: VRCX (Key is "Description" or Value contains "[Description]")
                elif key == "Description" or "[Description]" in raw_str:
                    # Look for JSON part starting with '{'
                    json_start = raw_str.find("{")
                    if json_start != -1:
                        json_data = raw_str[json_start:].strip()
                        try:
                            parsed_json = json.loads(json_data)
                            # Only display if it's explicitly from VRCX
                            if (
                                isinstance(parsed_json, dict)
                                and parsed_json.get("application") == "VRCX"
                            ):
                                should_display = True
                                display_value = json.dumps(
                                    parsed_json, indent=4, ensure_ascii=False
                                )
                        except json.JSONDecodeError:
                            pass

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
