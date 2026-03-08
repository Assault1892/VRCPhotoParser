import argparse
import json
import sys
import xml.dom.minidom
from datetime import datetime
from PIL import Image

# --- Utilities (Logic Only) ---

def normalize_vrc_date(raw_date_str):
    """Convert VRChat's ISO 8601 date to human-readable 'yyyy/mm/dd hh:mm:ss'."""
    if not raw_date_str or raw_date_str == "N/A":
        return "N/A"
    
    dt_str = str(raw_date_str).replace("Z", "+00:00")
    if "." in dt_str:
        # Normalize sub-seconds to 6 digits for Python compatibility
        parts = dt_str.split(".")
        base = parts[0]
        rest = parts[1]
        tz_split = rest.find("+") if "+" in rest else rest.find("-")
        if tz_split != -1:
            dt_str = f"{base}.{rest[:tz_split][:6]}{rest[tz_split:]}"
        else:
            dt_str = f"{base}.{rest[:6]}"
            
    try:
        return datetime.fromisoformat(dt_str).strftime("%Y/%m/%d %H:%M:%S")
    except:
        # Fallback for other potential formats
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y:%m:%d %H:%M:%S"):
            try:
                return datetime.strptime(raw_date_str, fmt).strftime("%Y/%m/%d %H:%M:%S")
            except:
                continue
    return raw_date_str

def extract_vrchat_xml_info(xml_str):
    """Extract specific VRChat fields from XMP XML string."""
    info = {}
    try:
        dom = xml.dom.minidom.parseString(xml_str)
        descriptions = dom.getElementsByTagName("rdf:Description")
        targets = {
            "CreateDate": ["xmp:CreateDate"],
            "Author": ["xmp:Author"],
            "WorldID": ["vrc:WorldID"],
            "WorldDisplayName": ["vrc:WorldDisplayName"],
            "AuthorID": ["vrc:AuthorID"],
        }
        for desc in descriptions:
            for key, tags in targets.items():
                if info.get(key): continue
                for tag in tags:
                    val = desc.getAttribute(tag)
                    if val:
                        info[key] = val
                        break
                if not info.get(key):
                    for tag in tags:
                        elements = desc.getElementsByTagName(tag)
                        if elements and elements[0].firstChild:
                            info[key] = elements[0].firstChild.nodeValue
                            break
        for key, tags in targets.items():
            if not info.get(key):
                for tag in tags:
                    elements = dom.getElementsByTagName(tag)
                    if elements and elements[0].firstChild:
                        info[key] = elements[0].firstChild.nodeValue
                        break
    except: pass
    return info

def parse_vrc_instance_id(instance_id):
    """Parse VRChat instanceId into human-readable components."""
    if not instance_id or ":" not in instance_id:
        return None
        
    parts = instance_id.split("~")
    base_part = parts[0].split(":")
    
    res = {
        "world_id": base_part[0],
        "id": base_part[1] if len(base_part) > 1 else "N/A",
        "type": "public",
        "owner_id": None,
        "group_id": None,
        "region": "us",
        "can_request_invite": False
    }
    
    for opt in parts[1:]:
        if opt == "canRequestInvite":
            res["can_request_invite"] = True
        elif opt.startswith("region("):
            res["region"] = opt[7:-1]
        elif opt.startswith("group("):
            res["group_id"] = opt[6:-1]
        elif opt.startswith("groupAccessType("):
            res["group_access_type"] = opt[16:-1]
        elif "(" in opt and opt.endswith(")"):
            idx = opt.find("(")
            res["type"] = opt[:idx]
            res["owner_id"] = opt[idx+1:-1]
        else:
            res["type"] = opt
            
    # Map internal types to display names
    if res["group_id"]:
        group_map = {"public": "Group Public", "plus": "Group+", "members": "Group Only"}
        res["display_type"] = group_map.get(res.get("group_access_type"), f"Group ({res.get('group_access_type')})")
    else:
        type_map = {"public": "Public", "hidden": "Friend+", "friends": "Friends", 
                    "private": "Invite+" if res["can_request_invite"] else "Invite"}
        res["display_type"] = type_map.get(res["type"], res["type"])
        
    region_map = {"jp": "日本", "us": "アメリカ西", "use": "アメリカ東", "eu": "ヨーロッパ"}
    res["display_region"] = region_map.get(res["region"], res["region"])
    
    return res

# --- Core Engine (No Side Effects/Prints) ---

def parse_photo_metadata(file_path):
    """Read PNG and return structured VRChat/VRCX metadata."""
    try:
        with Image.open(file_path) as img:
            if img.format != "PNG":
                return {"error": f"Not a PNG image (Format: {img.format})"}
            
            metadata = img.info
            result = {
                "file_path": file_path,
                "resolution": f"{img.width}x{img.height}",
                "vrchat": {},
                "vrcx": {},
                "consolidated": {}
            }

            # 1. XML (VRChat)
            vrchat_xml = metadata.get("XML:com.adobe.xmp")
            if vrchat_xml:
                xml_str = vrchat_xml.decode("utf-8", errors="ignore") if isinstance(vrchat_xml, bytes) else vrchat_xml
                result["vrchat"] = extract_vrchat_xml_info(xml_str)

            # 2. JSON (VRCX)
            for key, value in metadata.items():
                if isinstance(value, (str, bytes)):
                    raw_str = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else value
                    if "Description" in key or "[Description]" in raw_str:
                        json_start = raw_str.find("{")
                        if json_start != -1:
                            try:
                                parsed = json.loads(raw_str[json_start:])
                                if parsed.get("application") == "VRCX":
                                    result["vrcx"] = parsed
                                    break
                            except: pass

            # 3. Consolidation
            if result["vrchat"] or result["vrcx"]:
                vrcx_world = result["vrcx"].get("world", {})
                vrcx_author = result["vrcx"].get("author", {})
                
                result["consolidated"] = {
                    "datetime": normalize_vrc_date(result["vrchat"].get("CreateDate")),
                    "world_name": vrcx_world.get("name") or result["vrchat"].get("WorldDisplayName", "N/A"),
                    "world_id": vrcx_world.get("id") or result["vrchat"].get("WorldID", "N/A"),
                    "author_name": vrcx_author.get("displayName") or result["vrchat"].get("Author", "N/A"),
                    "author_id": vrcx_author.get("id") or result["vrchat"].get("AuthorID", "N/A"),
                    "instance": parse_vrc_instance_id(vrcx_world.get("instanceId")),
                    "players": result["vrcx"].get("players", [])
                }
            
            return result
    except Exception as e:
        return {"error": str(e)}

# --- CLI Output Logic ---

def print_cli_output(data):
    """Print structured data to terminal."""
    if "error" in data:
        print(f"Error: {data['error']}")
        return

    info = data["consolidated"]
    if not info:
        print("--- Photo Information ---")
        # print(f"Filename: {data['file_path']}")
        # print(f"Resolution: {data['resolution']}")
        print("\nNo VRChat or VRCX metadata found.")
        return

    print(f"--- Photo Information ---")
    if info["datetime"] != "N/A":
        print(f"日時: {info['datetime']}")
    print(f"ワールド: {info['world_name']} ({info['world_id']})")
    
    if info["instance"]:
        inst = info["instance"]
        print(f"インスタンス: {inst['display_type']} #{inst['id']} / Region: {inst['display_region']}")
        
    print(f"撮影者: {info['author_name']} ({info['author_id']})")

    if info["players"]:
        print(f"\n--- Players in Instance ({len(info['players'])}人) ---")
        for p in info["players"]:
            print(f"  - {p.get('displayName', 'N/A')} ({p.get('id', 'N/A')})")

def main():
    parser = argparse.ArgumentParser(
        description="Extract and display PNG metadata specifically for VRChat and VRCX."
    )
    parser.add_argument("file", help="Path to the PNG image file")

    args = parser.parse_args()
    data = parse_photo_metadata(args.file)
    print_cli_output(data)

if __name__ == "__main__":
    main()
