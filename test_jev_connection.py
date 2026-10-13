from techmedic.config import get_settings
from techmedic.jev import JevClient


def main() -> int:
    settings = get_settings()
    if not settings.jev_api_key:
        print("ERROR: JEV_API_KEY is missing from .env")
        return 1

    client = JevClient(
        settings.jev_api_key,
        settings.jev_model,
        endpoint=settings.jev_api_url,
        timeout=30,
    )

    print(f"Route   : {client.route_name}")
    print(f"Endpoint: {client.endpoint}")
    print(f"Model   : {settings.jev_model}")
    print("Testing...")

    try:
        result = client.test_connection()
    except Exception as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"SUCCESS: Jev returned model {result.get('model', 'unknown')}")
    answer = (result.get("answers") or {}).get("connected") or {}
    if "noul" in answer:
        print(f"Connectivity-test probability: {float(answer['noul']) * 100:.1f}%")
    usage = result.get("usage") or {}
    if usage:
        print(f"Input tokens: {usage.get('input_tokens', 'n/a')}")
        if usage.get("cost_usd") is not None:
            print(f"Cost USD    : {usage['cost_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
