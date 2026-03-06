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


def parse_vrc_instance_id(instance_id):
    """
    Parse VRChat instanceId into human-readable components.
    Public: world_id:instance_id~region(code)
    Friend+: world_id:instance_id~hidden(owner_id)~region(code)
    Friends: world_id:instance_id~friends(owner_id)~region(code)
    Invite+: world_id:instance_id~private(owner_id)~canRequestInvite~region(code)
    Invite: world_id:instance_id~private(owner_id)~region(code)
    Group: world_id:instance_id~group(id)~groupAccessType(type)~region(code)
    """
    if not instance_id or ":" not in instance_id:
        return None
        
    parts = instance_id.split("~")
    base_part = parts[0].split(":")
    
    res = {
        "world_id": base_part[0],
        "instance_id": base_part[1] if len(base_part) > 1 else "N/A",
        "owner_id": None,
        "group_id": None,
        "region": "us",
    }
    
    internal_type = "public"
    group_access_type = None
    can_request_invite = False
    
    for opt in parts[1:]:
        if opt == "canRequestInvite":
            can_request_invite = True
        elif opt.startswith("region("):
            res["region"] = opt[7:-1]
        elif opt.startswith("group("):
            res["group_id"] = opt[6:-1]
        elif opt.startswith("groupAccessType("):
            group_access_type = opt[16:-1]
        elif "(" in opt and opt.endswith(")"):
            idx = opt.find("(")
            internal_type = opt[:idx]
            res["owner_id"] = opt[idx+1:-1]
        else:
            internal_type = opt
            
    # Map types to human-friendly names
    if res["group_id"]:
        # Group instance mapping
        group_type_map = {
            "public": "Group Public",
            "plus": "Group+",
            "members": "Group Only"
        }
        res["instance_type"] = group_type_map.get(group_access_type, f"Group ({group_access_type})")
    else:
        # Regular instance mapping
        type_map = {
            "public": "Public",
            "hidden": "Friend+",
            "friends": "Friends",
            "private": "Invite+" if can_request_invite else "Invite"
        }
        res["instance_type"] = type_map.get(internal_type, internal_type)
    
    # Map region codes
    region_map = {
        "jp": "日本",
        "us": "アメリカ西",
        "use": "アメリカ東",
        "eu": "ヨーロッパ"
    }
    res["region"] = region_map.get(res["region"], res["region"])
    
    return res


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
                xml_str = (
                    vrchat_xml.decode("utf-8", errors="ignore")
                    if isinstance(vrchat_xml, bytes)
                    else vrchat_xml
                )
                vrchat_info = extract_vrchat_xml_info(xml_str)

            # Pre-scan for VRCX JSON info
            vrcx_info = {}
            for key, value in metadata.items():
                if isinstance(value, (str, bytes)):
                    raw_str = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else value
                    if "Description" in key or "[Description]" in raw_str:
                        json_start = raw_str.find("{")
                        if json_start != -1:
                            try:
                                parsed = json.loads(raw_str[json_start:])
                                if isinstance(parsed, dict) and parsed.get("application") == "VRCX":
                                    vrcx_info = parsed
                                    break
                            except:
                                pass

            # 1. Consolidated Photo Information
            if vrchat_info or vrcx_info:
                print(f"\n--- Photo Information ---")
                
                # Date (Prefer XML)
                display_date = vrchat_info.get("CreateDate", "N/A")
                if display_date != "N/A":
                    # Normalize sub-seconds
                    dt_str = display_date.replace("Z", "+00:00")
                    if "." in dt_str:
                        parts = dt_str.split(".")
                        base = parts[0]
                        rest = parts[1]
                        tz_split = rest.find("+") if "+" in rest else rest.find("-")
                        if tz_split != -1:
                            subseconds = rest[:tz_split]
                            timezone = rest[tz_split:]
                            dt_str = f"{base}.{subseconds[:6]}{timezone}"
                        else:
                            dt_str = f"{base}.{rest[:6]}"
                    try:
                        parsed_dt = datetime.fromisoformat(dt_str)
                        display_date = parsed_dt.strftime("%Y/%m/%d %H:%M:%S")
                    except:
                        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y:%m:%d %H:%M:%S"):
                            try:
                                parsed_dt = datetime.strptime(display_date, fmt)
                                display_date = parsed_dt.strftime("%Y/%m/%d %H:%M:%S")
                                break
                            except:
                                continue
                print(f"日時: {display_date}")

                # World Information
                world_name = vrcx_info.get("world", {}).get("name") or vrchat_info.get("WorldDisplayName", "N/A")
                world_id = vrcx_info.get("world", {}).get("id") or vrchat_info.get("WorldID", "N/A")
                print(f"ワールド: {world_name} ({world_id})")

                # Instance Details
                instance_id = vrcx_info.get("world", {}).get("instanceId")
                if instance_id:
                    parsed = parse_vrc_instance_id(instance_id)
                    if parsed:
                        print(f"インスタンス: {parsed['instance_type']} #{parsed['instance_id']} / Region: {parsed['region']}")

                # Author Information
                author_name = vrcx_info.get("author", {}).get("displayName") or vrchat_info.get("Author", "N/A")
                author_id = vrcx_info.get("author", {}).get("id") or vrchat_info.get("AuthorID", "N/A")
                print(f"撮影者: {author_name} ({author_id})")

            # 2. VRCX Player List
            players = vrcx_info.get("players", [])
            if players:
                print(f"\n--- Players in Instance ({len(players)}人) ---")
                for p in players:
                    print(f"  - {p.get('displayName', 'N/A')} ({p.get('id', 'N/A')})")

            # 3. Raw Metadata
            print(f"\n--- Raw Metadata (Targeted Chunks) ---")
            found_target = False
            for key, value in metadata.items():
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

                if key == "XML:com.adobe.xmp":
                    should_display = True
                    try:
                        dom = xml.dom.minidom.parseString(raw_str)
                        pretty_xml = dom.toprettyxml(indent="    ")
                        lines = pretty_xml.splitlines()
                        start_idx = 1 if lines and lines[0].strip().startswith("<?xml") else 0
                        display_value = "\n".join([line for line in lines[start_idx:] if line.strip()])
                    except:
                        pass
                elif key == "Description" or "[Description]" in raw_str:
                    json_start = raw_str.find("{")
                    if json_start != -1:
                        try:
                            parsed_json = json.loads(raw_str[json_start:])
                            if isinstance(parsed_json, dict) and parsed_json.get("application") == "VRCX":
                                should_display = True
                                display_value = json.dumps(parsed_json, indent=4, ensure_ascii=False)
                        except:
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
