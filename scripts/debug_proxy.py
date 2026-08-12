import requests

from news_collector.infrastructure.proxy_manager import proxy_manager


def reproduce_error():
    config = {"proxy_mode": "auto", "name": "test"}
    resp = requests.Response()
    resp.status_code = 403

    try:
        res = proxy_manager.should_retry_with_proxy(config, response=resp)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Caught error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    reproduce_error()
