"""Background cache refresh entry point.

Called by cache.refresh_cache_background() as a detached subprocess.
Fetches fresh data from claude-monitor and writes to cache.
"""

from .core import try_original_analysis, direct_data_analysis, calculate_reset_time
from .cache import write_cache


def main():
    usage_data = try_original_analysis()
    if not usage_data:
        usage_data = direct_data_analysis()
    if usage_data:
        reset_time = calculate_reset_time()
        usage_data["_reset_time"] = reset_time
        write_cache(usage_data)


if __name__ == "__main__":
    main()
