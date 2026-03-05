import urllib.request
import json

url = "http://localhost:8080/api/v1/system/status"
try:
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error fetching status: {e}")
