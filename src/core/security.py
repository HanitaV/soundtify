import os
import json
import hashlib

def get_appdata_dir() -> str:
    appdata = os.getenv('APPDATA')
    if appdata:
        path = os.path.join(appdata, 'soundtify')
    else:
        path = os.path.join(os.path.expanduser('~'), '.soundtify')
    os.makedirs(path, exist_ok=True)
    return path

def calculate_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def secure_save_json(filename: str, data: dict):
    path = get_appdata_dir()
    file_path = os.path.join(path, filename)
    hash_path = os.path.join(path, filename + '.sha256')
    
    json_bytes = json.dumps(data, indent=4).encode('utf-8')
    checksum = calculate_sha256(json_bytes)
    
    with open(file_path, 'wb') as f:
        f.write(json_bytes)
        
    with open(hash_path, 'w', encoding='utf-8') as f:
        f.write(checksum)

def secure_load_json(filename: str) -> dict:
    path = get_appdata_dir()
    file_path = os.path.join(path, filename)
    hash_path = os.path.join(path, filename + '.sha256')
    
    if not os.path.exists(file_path) or not os.path.exists(hash_path):
        return {}
        
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
            
        with open(hash_path, 'r', encoding='utf-8') as f:
            expected_hash = f.read().strip()
            
        if calculate_sha256(data) != expected_hash:
            # File corrupted or tampered
            return {}
            
        return json.loads(data.decode('utf-8'))
    except Exception:
        return {}
