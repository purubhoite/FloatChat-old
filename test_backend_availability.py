import requests
import json
import sys

def test_backend():
    url = "http://localhost:8000/ask"
    payload = {"query": "Show me salinity profiles near the equator"}
    try:
        print(f"Sending request to {url}...")
        r = requests.post(url, json=payload, timeout=30)
        print(f"Status Code: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print("Response OK")
            print("Explanation prefix:", data.get("explanation", "")[:50])
            print("Has Rows:", bool(data.get("data", {}).get("rows")))
            print("Has Viz:", bool(data.get("viz")))
        else:
            print("Error response:", r.text)
    except Exception as e:
        print(f"Failed to connect to backend: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_backend()
