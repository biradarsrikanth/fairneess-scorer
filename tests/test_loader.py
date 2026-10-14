"""The data loader's cache."""
import threading
import time

import pandas as pd

from src.db.loader import DataLoader


def test_concurrent_requests_for_the_same_data_load_it_once():
    loads = []

    def slow_load() -> pd.DataFrame:
        loads.append(1)
        time.sleep(0.2)
        return pd.DataFrame({"x": [1]})

    loader = DataLoader(engine=None, ttl_seconds=60)  # type: ignore[arg-type]
    results = []
    threads = [threading.Thread(target=lambda: results.append(loader._cached(("q",), slow_load)))
               for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(loads) == 1
    assert len(results) == 5 and all(r["x"].tolist() == [1] for r in results)
    # Each caller has its own copy
    assert len({id(r) for r in results}) == 5
