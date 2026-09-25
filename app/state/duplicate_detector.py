import hashlib

class DuplicateDetector:
    _seen_hashes = set()

    @staticmethod
    def generate_hash(symbol: str, direction: str, setup_name: str, entry_price: float, timestamp_bucket: str) -> str:
        raw_str = f"{symbol}_{direction}_{setup_name}_{round(entry_price, 2)}_{timestamp_bucket}"
        return hashlib.sha256(raw_str.encode()).hexdigest()

    @classmethod
    def is_duplicate(cls, signal_hash: str) -> bool:
        if signal_hash in cls._seen_hashes:
            return True
        cls._seen_hashes.add(signal_hash)
        return False
