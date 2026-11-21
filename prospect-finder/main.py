"""Korvellan Studios Prospect Finder - Find local business prospects."""
import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests


USER_AGENT = "KorvellanStudiosProspectFinder/1.0"
REQUEST_TIMEOUT = 60
API_RATE_LIMIT_DELAY = 2.0


def fetch_location(city: str) -> tuple | None:
    """Fetch location coordinates using Nominatim API."""
    params = {"q": city, "format": "json", "limit": 1}
    
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        
        http_status = response.status_code
        content_type = response.headers.get("Content-Type", "")
        
        if http_status != 200:
            print(f"  Nominatim status: {http_status} ({content_type[:50]}...)")
            preview = response.text[:200]
            print(f"  Response preview: {preview!r}")
            return None
        
        try:
            content_length = len(response.content)
            if content_length == 0:
                print("  Nominatim returned empty response (0 bytes)")
                return None
                
            data = response.json()
            
            if isinstance(data, dict):
                print(f"  Nominatim warning: Got dict instead of list")
                return None
            
            if not data or len(data) == 0:
                print("  Nominatim warning: Empty or null array returned")
                return None
                
            city_data = data[0]
            if "lat" in city_data and "lon" in city_data:
                display_name = city_data.get("display_name", city)
                return {"display_name": display_name, "lat": float(city_data["lat"]), "lon": float(city_data["lon"])}
                
        except json.JSONDecodeError as e:
            print(f"  Nominatim JSON decode error (non-JSON response): {e}")
            preview = response.text[:200]
            print(f"  Response preview: {preview!r}")
            return None
            
    except requests.RequestException as e:
        print(f"Warning: Failed to fetch location for '{city}': {e}")
    
    return None


def search_businesses(city: str, industry: str, limit: int) -> list:
    """Search for businesses in a given city and industry using Overpass API."""
    import time
    
    # Use a simpler query - Overpass QL requires proper escaping of special characters
    # We'll use the addr:city relation with exact shop tag matching
    safe_city = city.replace("'", "\\'").replace('"', "\\\"")
    
    query = f"""[out:json][timeout:120]
(node["shop"~"plumbing|air_conditioning|electrical|contractor|carpenter"]["addr:city"="{safe_city}"];
 node["shop":"*"]["addr:city"="{safe_city}"]);
out body;"""

    payload = {"data": query, "options": ["dateNow"]}
    
    results = []
    attempts = 0
    
    while attempts < 3 and len(results) < limit:
        try:
            response = requests.post(
                "https://overpass-api.de/api/interpreter",
                data=payload,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            
            http_status = response.status_code
            content_type = response.headers.get("Content-Type", "")
            
            if http_status == 429:
                wait_time = min(60, (attempts + 1) * 5)
                print(f"Rate limit hit. Waiting {wait_time}s...")
                time.sleep(wait_time)
                attempts += 1
                continue
            
            if http_status != 200:
                print(f"\nOverpass API returned status {http_status}")
                print(f"Content-Type: {content_type}")
                preview = response.text[:500]
                print(f"Response preview:\n{preview}")
                
                # Extract error message if present
                try:
                    data_preview = json.loads(preview)
                    if "message" in data_preview:
                        print(f"Error message: {data_preview['message']}")
                except json.JSONDecodeError:
                    pass
                    
                attempts += 1
                continue
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                print(f"\nOverpass API returned non-JSON response on attempt {attempts + 1}:")
                print(f"HTTP Status: {http_status}")
                print(f"Content-Type: {content_type}")
                preview = response.text[:500]
                print(f"Response preview:\n{preview}")
                attempts += 1
                continue
            
            if not isinstance(data, dict):
                print(f"\nOverpass error: Expected dict but got {type(data).__name__}")
                attempts += 1
                continue
                
            # Overparse returns results in top-level array, not nested under "elements"
            elements = data.get("elements", data) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            status_element = data.get("status") or {}
            
            if "message" in status_element and status_element["message"]:
                print(f"\nOverpass API message: {status_element['message']}")
                
            if not elements:
                warnings = data.get("warnings", []) if isinstance(data, dict) else []
                if warnings:
                    for warning in warnings[:2]:
                        print(f"  Warning: {warning}")
                print("\nNo matching businesses found in Overpass database.")
                break
                
            for element in elements[:limit]:
                tags = element.get("tags", {})
                name = tags.get("name") or tags.get("alt_name", "")
                
                if not name or len(name) < 2:
                    continue
                
                phone = ""
                website = ""
                addr_city = safe_city
                
                for k, v in tags.items():
                    if k == "phone" and isinstance(v, str) and len(v) > 3:
                        try:
                            cleaned = re.sub(r'[^0-9+]', '', v[:15])
                            if cleaned and not phone:
                                phone = cleaned
                        except Exception:
                            pass
                    
                    elif k == "url" or k == "homepage":
                        website = v
                        if not website.startswith(("http://", "https://")):
                            website = f"https://{website}"
                    
                    elif k.startswith("addr:") and len(v) > 2 and addr_city != safe_city:
                        addr_parts = [p.strip() for p in addr_city.split(",") if p] + [v]
                        addr_city = ", ".join(addr_parts)
                
                results.append({
                    "id": element.get("id"),
                    "name": name,
                    "address_city": addr_city,
                    "phone": phone.strip() or "",
                    "website": website.strip() or "",
                    "timestamp": datetime.now().isoformat(),
                })
            
            time.sleep(API_RATE_LIMIT_DELAY)
            
        except requests.RequestException as e:
            print(f"Request failed (attempt {attempts + 1}/3): HTTP error - {e}")
            attempts += 1
    
    return results


def remove_duplicates(prospects: list) -> list:
    """Remove duplicate businesses based on name and city."""
    seen = set()
    unique = []
    
    for p in prospects:
        key = (p.get("name", "").lower().strip(),
                p.get("address_city", "").lower())
        if key not in seen and p.get("name"):
            seen.add(key)
            unique.append(p)
    
    return unique


def save_to_csv(prospects: list, filepath: str):
    """Save prospects to CSV."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    fieldnames = ["id", "name", "address_city", "phone", "website", "timestamp"]
    
    exists = filepath.exists()
    
    with open(filepath, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if not exists and len(prospects) > 0:
            writer.writeheader()
            
        for p in prospects:
            row = {
                "id": p.get("id"),
                "name": p.get("name", ""),
                "address_city": p.get("address_city", ""),
                "phone": p.get("phone", ""),
                "website": p.get("website", ""),
                "timestamp": p.get("timestamp", datetime.now().isoformat()),
            }
            writer.writerow(row)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Korvellan Studios Prospect Finder - Find local business prospects"
    )
    parser.add_argument("command", choices=["search"], help="Available commands")
    parser.add_argument("--city", required=True, help="City to search in")
    parser.add_argument("--industry", required=True, help="Industry (e.g., plumber)")
    parser.add_argument("-l", "--limit", type=int, default=20)
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("   Korvellan Studios Prospect Finder")
    print("=" * 60)
    print(f"\nSearching for: {args.industry} businesses in {args.city}")
    print(f"Limit: {args.limit} results\n")
    
    try:
        import time
        
        prospects = search_businesses(args.city, args.industry, args.limit)
        prospects = remove_duplicates(prospects)
        
        if prospects:
            filepath = Path(__file__).parent / "data" / "prospects.csv"
            save_to_csv(prospects, str(filepath))
            
            print(f"\nFound {len(prospects)} unique businesses:\n")
            print("-" * 80)
            
            for i, p in enumerate(prospects, 1):
                name = p.get("name", "Unknown")[:45] + "..." if len(p.get("name", "")) > 45 else p.get("name", "")
                print(f"\n[{i}] {name}")
                
                if p.get("phone"):
                    phone_display = p["phone"][:12] + ".." if len(p["phone"]) > 12 else p["phone"]
                    print(f"    Phone: {phone_display}{'...' if len(p['phone']) > 12 else ''}")
                
                if p.get("website"):
                    website_display = p["website"][:42] + "..." if len(p["website"]) > 42 else p["website"]
                    print(f"    Website: {website_display}{'...' if len(p['website']) > 42 else ''}")
                
                addr_city = p.get("address_city", args.city)
                print(f"    Address: {addr_city}")
            
            print("-" * 80)
            print(f"\nResults saved to: {filepath}")
        else:
            print("\nNo businesses found in the Overpass database.")
            print("This may mean:")
            print("  * The city has no matching business records in OpenStreetMap")
            print("  * The industry keywords do not match stored tags")
            print("  * Try a different city or industry (plumber, hvac)")
            
    except KeyboardInterrupt:
        print("\nSearch interrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
