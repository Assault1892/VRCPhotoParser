import argparse
import asyncio
import json
import locale
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime

import aiofiles

# --- Language Resources ---

LANGUAGES = {
    "ja": {
        "datetime": "日時",
        "world": "ワールド",
        "instance": "インスタンス",
        "author": "撮影者",
        "region": "地域",
        "players": "インスタンスにいたプレイヤー",
        "photo_info_header": "写真の情報",
        "players_count": "{}人",
        "no_metadata": "VRChat または VRCX のメタデータが見つかりませんでした。",
        "error_not_png": "PNG画像ではありません (Format: {})",
        "error_file_not_found": "ファイルが見つかりません: {}",
        "region_names": {
            "jp": "日本",
            "us": "アメリカ西",
            "use": "アメリカ東",
            "eu": "ヨーロッパ",
        },
    },
    "en": {
        "datetime": "Date/Time",
        "world": "World",
        "instance": "Instance",
        "author": "Author",
        "region": "Region",
        "players": "Players in Instance",
        "photo_info_header": "Photo Information",
        "players_count": "{} players",
        "no_metadata": "No VRChat or VRCX metadata found.",
        "error_not_png": "Not a PNG image (Format: {})",
        "error_file_not_found": "File not found: {}",
        "region_names": {
            "jp": "Japan",
            "us": "US West",
            "use": "US East",
            "eu": "Europe",
        },
    },
}


def get_translator():
    """Get the appropriate translator based on system locale."""
    try:
        sys_lang = locale.getdefaultlocale()[0]
        lang_code = sys_lang[:2] if sys_lang else "en"
    except:
        lang_code = "en"
    return LANGUAGES.get(lang_code, LANGUAGES["en"])


t = get_translator()

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
        for fmt in (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y:%m:%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(raw_date_str, fmt).strftime(
                    "%Y/%m/%d %H:%M:%S"
                )
            except:
                continue
    return raw_date_str


def extract_vrchat_xml_info(xml_str):
    """Extract VRChat fields from XMP XML using robust namespace handling."""
    info = {}
    try:
        ns = {
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "xmp": "http://ns.adobe.com/xap/1.0/",
            "vrc": "http://vrchat.com/xmp/1.0/",
        }
        root = ET.fromstring(xml_str)
        descriptions = root.findall(".//rdf:Description", ns)
        for desc in descriptions:
            for key, tag in [
                ("CreateDate", "{http://ns.adobe.com/xap/1.0/}CreateDate"),
                ("Author", "{http://ns.adobe.com/xap/1.0/}Author"),
                ("WorldID", "{http://vrchat.com/xmp/1.0/}WorldID"),
                ("WorldDisplayName", "{http://vrchat.com/xmp/1.0/}WorldDisplayName"),
                ("AuthorID", "{http://vrchat.com/xmp/1.0/}AuthorID"),
            ]:
                if not info.get(key):
                    val = desc.get(tag)
                    if val:
                        info[key] = val
            for key, xpath in [
                ("CreateDate", ".//xmp:CreateDate"),
                ("Author", ".//xmp:Author"),
                ("WorldID", ".//vrc:WorldID"),
                ("WorldDisplayName", ".//vrc:WorldDisplayName"),
                ("AuthorID", ".//vrc:AuthorID"),
            ]:
                if not info.get(key):
                    el = desc.find(xpath, ns)
                    if el is not None and el.text:
                        info[key] = el.text
        if not all(k in info for k in ["CreateDate", "Author", "WorldID"]):
            for key, xpath in [
                ("CreateDate", ".//xmp:CreateDate"),
                ("Author", ".//xmp:Author"),
                ("WorldID", ".//vrc:WorldID"),
                ("WorldDisplayName", ".//vrc:WorldDisplayName"),
                ("AuthorID", ".//vrc:AuthorID"),
            ]:
                if not info.get(key):
                    el = root.find(xpath, ns)
                    if el is not None and el.text:
                        info[key] = el.text
    except Exception:
        pass
    return info


def parse_vrc_instance_id(instance_id):
    """Parse VRChat instanceId into human-readable components."""
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
    internal_type, group_access_type, can_request_invite = "public", None, False
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
            internal_type, res["owner_id"] = opt[:idx], opt[idx + 1 : -1]
        else:
            internal_type = opt
    if res["group_id"]:
        group_map = {
            "public": "Group Public",
            "plus": "Group+",
            "members": "Group Only",
        }
        res["instance_type"] = group_map.get(
            group_access_type, f"Group ({group_access_type})"
        )
    else:
        type_map = {
            "public": "Public",
            "hidden": "Friend+",
            "friends": "Friends",
            "private": "Invite+" if can_request_invite else "Invite",
        }
        res["instance_type"] = type_map.get(internal_type, internal_type)
    res["display_region"] = t["region_names"].get(res["region"], res["region"])
    return res


async def read_png_chunks_async(file_path):
    """Fast PNG chunk reader to extract metadata without full image decode (Async)."""
    chunks = {}
    resolution = "Unknown"
    try:
        async with aiofiles.open(file_path, "rb") as f:
            sig = await f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return None, None
            while True:
                length_bytes = await f.read(4)
                if not length_bytes:
                    break
                length = struct.unpack(">I", length_bytes)[0]
                chunk_type_bytes = await f.read(4)
                chunk_type = chunk_type_bytes.decode("ascii", errors="ignore")
                data = await f.read(length)
                await f.read(4)  # CRC
                if chunk_type == "IHDR":
                    w, h = struct.unpack(">II", data[:8])
                    resolution = f"{w}x{h}"
                elif chunk_type == "tEXt":
                    parts = data.split(b"\x00", 1)
                    if len(parts) == 2:
                        chunks[parts[0].decode("latin-1", errors="ignore")] = parts[
                            1
                        ].decode("latin-1", errors="ignore")
                elif chunk_type == "zTXt":
                    parts = data.split(b"\x00", 2)
                    if len(parts) >= 2:
                        key = parts[0].decode("latin-1", errors="ignore")
                        try:
                            compressed_data = parts[2] if len(parts) > 2 else b""
                            text = zlib.decompress(compressed_data).decode(
                                "utf-8", errors="ignore"
                            )
                            chunks[key] = text
                        except:
                            pass
                elif chunk_type == "iTXt":
                    parts = data.split(b"\x00", 5)
                    if len(parts) >= 6:
                        key = parts[0].decode("utf-8", errors="ignore")
                        text = parts[5].decode("utf-8", errors="ignore")
                        if parts[1] == b"\x01":
                            try:
                                text = zlib.decompress(parts[5]).decode(
                                    "utf-8", errors="ignore"
                                )
                            except:
                                pass
                        chunks[key] = text
                elif chunk_type == "IEND":
                    break
    except Exception:
        pass
    return chunks, resolution


# --- Core Engine ---


async def parse_photo_metadata_async(file_path):
    """Read PNG metadata efficiently and asynchronously."""
    try:
        metadata, resolution = await read_png_chunks_async(file_path)
        if metadata is None:
            return {"error": t["error_not_png"].format("Unknown")}

        result = {
            "file_path": file_path,
            "resolution": resolution,
            "vrchat": {},
            "vrcx": {},
            "consolidated": {},
        }

        # 1. XML (VRChat)
        vrchat_xml = metadata.get("XML:com.adobe.xmp") or metadata.get("com.adobe.xmp")
        if vrchat_xml:
            result["vrchat"] = extract_vrchat_xml_info(vrchat_xml)

        # 2. JSON (VRCX)
        for key, value in metadata.items():
            if "Description" in key or "[Description]" in value:
                json_start = value.find("{")
                if json_start != -1:
                    try:
                        parsed = json.loads(value[json_start:])
                        if parsed.get("application") == "VRCX":
                            result["vrcx"] = parsed
                            break
                    except:
                        pass

        # 3. Consolidation
        if result["vrchat"] or result["vrcx"]:
            vrcx_world = result["vrcx"].get("world", {})
            vrcx_author = result["vrcx"].get("author", {})
            result["consolidated"] = {
                "datetime": normalize_vrc_date(result["vrchat"].get("CreateDate")),
                "world_name": vrcx_world.get("name")
                or result["vrchat"].get("WorldDisplayName", "N/A"),
                "world_id": vrcx_world.get("id")
                or result["vrchat"].get("WorldID", "N/A"),
                "author_name": vrcx_author.get("displayName")
                or result["vrchat"].get("Author", "N/A"),
                "author_id": vrcx_author.get("id")
                or result["vrchat"].get("AuthorID", "N/A"),
                "instance": parse_vrc_instance_id(vrcx_world.get("instanceId")),
                "players": result["vrcx"].get("players", []),
            }
        return result
    except FileNotFoundError:
        return {"error": t["error_file_not_found"].format(file_path)}
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
        print(f"--- {t['photo_info_header']} ---")
        print(f"\n{t['no_metadata']}")
        return
    print(f"--- {t['photo_info_header']} ---")
    if info["datetime"] != "N/A":
        print(f"{t['datetime']}: {info['datetime']}")
    print(f"{t['world']}: {info['world_name']} ({info['world_id']})")
    if info["instance"]:
        inst = info["instance"]
        print(
            f"{t['instance']}: {inst['instance_type']} #{inst['instance_id']} / {t['region']}: {inst['display_region']}"
        )
    print(f"{t['author']}: {info['author_name']} ({info['author_id']})")
    if info["players"]:
        print(
            f"\n--- {t['players']} ({t['players_count'].format(len(info['players']))}) ---"
        )
        for p in info["players"]:
            print(f"  - {p.get('displayName', 'N/A')} ({p.get('id', 'N/A')})")


async def main():
    parser = argparse.ArgumentParser(
        description="Extract and display PNG metadata specifically for VRChat and VRCX."
    )
    parser.add_argument("file", help="Path to the PNG image file")
    args = parser.parse_args()
    data = await parse_photo_metadata_async(args.file)
    print_cli_output(data)


if __name__ == "__main__":
    asyncio.run(main())
