import argparse
import json
import sys
import xml.dom.minidom
from datetime import datetime

from PIL import Image
from PIL.PngImagePlugin import PngInfo


def extract_vrchat_xml_info(xml_str):
    """Extract specific VRChat fields from XMP XML string."""
    info = {}
    try:
        dom = xml.dom.minidom.parseString(xml_str)
        # XMP data is usually inside rdf:Description
        descriptions = dom.getElementsByTagName("rdf:Description")

        # Tags to look for (both as attributes and nested elements)
        targets = {
            "CreateDate": ["xmp:CreateDate"],
            "Author": ["xmp:Author"],
            "WorldID": ["vrc:WorldID"],
            "WorldDisplayName": ["vrc:WorldDisplayName"],
            "AuthorID": ["vrc:AuthorID"],
        }

        for desc in descriptions:
            for key, tags in targets.items():
                if info.get(key):
                    continue
                # Try attributes first
                for tag in tags:
                    val = desc.getAttribute(tag)
                    if val:
                        info[key] = val
                        break
                # Try nested elements if not found as attribute
                if not info.get(key):
                    for tag in tags:
                        elements = desc.getElementsByTagName(tag)
                        if elements and elements[0].firstChild:
                            info[key] = elements[0].firstChild.nodeValue
                            break

        # If not in rdf:Description, search globally
        for key, tags in targets.items():
            if not info.get(key):
                for tag in tags:
                    elements = dom.getElementsByTagName(tag)
                    if elements and elements[0].firstChild:
                        info[key] = elements[0].firstChild.nodeValue
                        break
    except Exception:
        pass
    return info


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

            # Pre-scan for VRChat XML info
            vrchat_xml = metadata.get("XML:com.adobe.xmp")
            vrchat_info = {}
            if vrchat_xml:
                # Handle bytes if necessary
                xml_str = (
                    vrchat_xml.decode("utf-8", errors="ignore")
                    if isinstance(vrchat_xml, bytes)
                    else vrchat_xml
                )
                vrchat_info = extract_vrchat_xml_info(xml_str)

            if vrchat_info:
                # Format CreateDate if possible for human readability
                display_date = vrchat_info.get("CreateDate", "N/A")
                if display_date != "N/A":
                    # Try various parsing methods
                    parsed_dt = None
                    
                    # Normalize the date string for Python's datetime.fromisoformat
                    # 1. Replace 'Z' with UTC offset
                    # 2. Handle sub-second precision: datetime only supports up to 6 digits (microseconds)
                    # Example: 2026-02-22T03:49:33.9841309+09:00 -> truncation needed
                    dt_str = display_date.replace("Z", "+00:00")
                    if "." in dt_str:
                        # Split by '.' and '+' or '-' for timezone
                        parts = dt_str.split(".")
                        base = parts[0]
                        rest = parts[1]
                        
                        # Find timezone separator (+ or -) in the rest
                        tz_split = rest.find("+") if "+" in rest else rest.find("-")
                        if tz_split != -1:
                            subseconds = rest[:tz_split]
                            timezone = rest[tz_split:]
                            # Truncate subseconds to 6 digits
                            dt_str = f"{base}.{subseconds[:6]}{timezone}"
                        else:
                            # No timezone found, just truncate subseconds
                            dt_str = f"{base}.{rest[:6]}"

                    # Try fromisoformat
                    try:
                        parsed_dt = datetime.fromisoformat(dt_str)
                    except Exception:
                        pass
                    
                    # Fallback to common XMP/ISO patterns
                    if not parsed_dt:
                        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y:%m:%d %H:%M:%S"):
                            try:
                                parsed_dt = datetime.strptime(display_date, fmt)
                                break
                            except Exception:
                                continue
                    
                    if parsed_dt:
                        display_date = parsed_dt.strftime("%Y/%m/%d %H:%M:%S")

                print(f"\n--- VRChat Photo Information ---")
                print(f"日時: {display_date}")
                print(f"ワールド名: {vrchat_info.get('WorldDisplayName', 'N/A')}")
                print(f"ワールドID: {vrchat_info.get('WorldID', 'N/A')}")
                print(f"撮影者: {vrchat_info.get('Author', 'N/A')}")
                print(f"撮影者ID: {vrchat_info.get('AuthorID', 'N/A')}")

            print(f"\n--- PNG Metadata (VRChat / VRCX Raw) ---")
            found_target = False
            for key, value in metadata.items():
                # Handle bytes values
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

                # Target 1: VRChat Metadata (XML:com.adobe.xmp)
                if key == "XML:com.adobe.xmp":
                    should_display = True
                    try:
                        dom = xml.dom.minidom.parseString(raw_str)
                        # Pretty print the XML
                        pretty_xml = dom.toprettyxml(indent="    ")
                        # Filter out XML declaration and empty lines
                        lines = pretty_xml.splitlines()
                        # Skip the first line if it's the XML declaration (<?xml ... ?>)
                        start_idx = (
                            1 if lines and lines[0].strip().startswith("<?xml") else 0
                        )
                        display_value = "\n".join(
                            [line for line in lines[start_idx:] if line.strip()]
                        )
                    except Exception:
                        # Fallback to raw string if XML parsing fails
                        pass

                # Target 2: VRCX Metadata (JSON found in "Description" chunk)
                elif key == "Description" or "[Description]" in raw_str:
                    # VRCX stores metadata in JSON format after "[Description]" prefix
                    json_start = raw_str.find("{")
                    if json_start != -1:
                        json_data = raw_str[json_start:].strip()
                        try:
                            parsed_json = json.loads(json_data)
                            # Verify if the application key is "VRCX"
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
                print("No VRChat or VRCX metadata found in this image.")

    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
    except Exception as e:
        print(f"Error: An unexpected error occurred: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract and display PNG metadata specifically for VRChat and VRCX."
    )
    parser.add_argument("file", help="Path to the PNG image file")

    args = parser.parse_args()
    parse_png_metadata(args.file)


if __name__ == "__main__":
    main()
