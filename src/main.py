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

            print(f"\n--- PNG Metadata (Text Chunks) ---")
            for key, value in metadata.items():
                # VRChat and other tools often store JSON in these chunks
                display_value = value
                if isinstance(value, str):
                    trimmed = value.strip()
                    if (trimmed.startswith("{") and trimmed.endswith("}")) or (
                        trimmed.startswith("[") and trimmed.endswith("]")
                    ):
                        try:
                            # Try to pretty-print JSON if possible
                            parsed_json = json.loads(trimmed)
                            display_value = json.dumps(
                                parsed_json, indent=4, ensure_ascii=False
                            )
                        except json.JSONDecodeError:
                            pass

                print(f"[{key}]:")
                print(display_value)
                print("-" * 20)

    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
    except Exception as e:
        print(f"Error: An unexpected error occurred: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract and display PNG metadata (text chunks)."
    )
    parser.add_argument("file", help="Path to the PNG image file")

    args = parser.parse_args()
    parse_png_metadata(args.file)


if __name__ == "__main__":
    main()
