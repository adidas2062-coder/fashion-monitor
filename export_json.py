import os
import json
import logging
from api_server import _collect_monitoring, _simulate_sales, _collect_events, _kst_now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("json_exporter")

def export_all():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data", "json")
    os.makedirs(data_dir, exist_ok=True)
    
    logger.info("Collecting monitoring data...")
    monitoring = _collect_monitoring()
    
    logger.info("Simulating sales data...")
    sales = _simulate_sales()
    
    logger.info("Collecting events data...")
    events = _collect_events()
    
    def save_json(filename, data, count=None):
        filepath = os.path.join(data_dir, filename)
        payload = {
            "ok": True,
            "updated_at": _kst_now().isoformat(),
            "data": data
        }
        if count is not None:
            payload["count"] = count
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {filename}")

    save_json("monitoring.json", monitoring)
    save_json("sales.json", sales)
    save_json("events.json", events, count=len(events))
    
    logger.info("JSON export completed.")

if __name__ == "__main__":
    export_all()
